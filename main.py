
# main.py
import os
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from jose import jwt, JWTError
import modal
from dotenv import load_dotenv

# --------------------------
# Charger les variables d'environnement
# --------------------------
load_dotenv()
JWT_SECRET = os.getenv("JWT_SECRET")           # Secret partagé pour JWT
JWT_ALGO = os.getenv("JWT_ALGO", "HS256")      # Algorithme JWT

# --------------------------
# Auth JWT
# --------------------------
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return {"id": payload.get("sub"), "email": payload.get("email")}
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré")

# --------------------------
# FastAPI app
# --------------------------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # front-end
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------
# Modal sandbox
# --------------------------
# Image avec vos dépendances (requirements.txt doit contenir openai par exemple)
image = modal.Image.debian_slim().pip_install_from_requirements("requirements.txt")

# Créer un volume persistant pour stocker fichiers
volume = modal.Volume.from_name("sandbox-storage", create_if_missing=True)

app_modal = modal.App("sandbox-microservice", image=image)

# --------------------------
# Fonctions sandbox
# --------------------------
# Fonction IA pour compléter un prompt
@app_modal.function(secrets=[modal.Secret.from_name("openai-secret")])
def complete_text(prompt: str):
    from openai import OpenAI
    client = OpenAI()
    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="gpt-4.1"
    )
    return chat_completion.choices[0].message.content

# Fonction pour écrire un fichier dans le volume
@app_modal.function(volumes={"/sandbox": volume})
def write_file(filename: str, content: str):
    path = f"/sandbox/{filename}"
    with open(path, "w") as f:
        f.write(content)
    return f"File '{filename}' saved."

# Fonction pour lire un fichier depuis le volume
@app_modal.function(volumes={"/sandbox": volume})
def read_file(filename: str):
    path = f"/sandbox/{filename}"
    if not os.path.exists(path):
        return f"File '{filename}' not found."
    with open(path, "r") as f:
        return f.read()

# --------------------------
# Endpoints FastAPI
# --------------------------
class SandboxRequest(BaseModel):
    prompt: str

class FileRequest(BaseModel):
    filename: str
    content: str = None  # facultatif pour read

# Lancer un prompt IA
@app.post("/sandbox/prompt")
def sandbox_prompt(data: SandboxRequest, user=Depends(get_current_user)):
    with app_modal.run():
        result = complete_text.remote(data.prompt)  # renvoie déjà le résultat
    return { "response": result}

# Créer ou éditer un fichier
@app.post("/sandbox/write")
def sandbox_write_file(data: FileRequest, user=Depends(get_current_user)):
    if data.content is None:
        raise HTTPException(status_code=400, detail="Content is required to write a file")
    with app_modal.run():
        result = write_file.remote(data.filename, data.content)
    return { "message": result}

# Lire un fichier
@app.get("/sandbox/read")
def sandbox_read_file(filename: str, user=Depends(get_current_user)):
    with app_modal.run():
        result = read_file.remote(filename)
    return {"content": result}

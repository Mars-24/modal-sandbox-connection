# main.py
import os
from fastapi import FastAPI, Depends, HTTPException, UploadFile
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
JWT_SECRET = os.getenv("JWT_SECRET", "changeme")
JWT_ALGO = os.getenv("JWT_ALGO", "HS256")
NGROK_TOKEN = os.getenv("NGROK_AUTHTOKEN")
    
print(f"Token {NGROK_TOKEN}")
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
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------
# Modal sandbox
# --------------------------
#image = modal.Image.debian_slim().pip_install_from_requirements("requirements.txt")
image = (
    modal.Image.debian_slim()
    # Installer curl pour NodeSource
    .apt_install("curl", "unzip","wget")

    # Installer Node.js 20 et npm
    .run_commands([
        "curl -fsSL https://deb.nodesource.com/setup_20.x | bash -",
        "apt-get install -y nodejs"
    ])
    # Installer les dépendances Python
    .pip_install_from_requirements("requirements.txt")
)
volume = modal.Volume.from_name("sandbox-storage", create_if_missing=True)
app_modal = modal.App("sandbox-microservice", image=image)



# --------------------------
# Fonctions Modal
# --------------------------

# Prompt IA
@app_modal.function(secrets=[modal.Secret.from_name("openai-secret")])
def complete_text(prompt: str):
    from openai import OpenAI
    client = OpenAI()
    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="gpt-4.1"
    )
    return chat_completion.choices[0].message.content



# Écrire un fichier texte
@app_modal.function(volumes={"/sandbox": volume})
def write_file(filename: str, content: str):
    path = f"/sandbox/{filename}"
    with open(path, "w") as f:
        f.write(content)
    return f"File '{filename}' saved."

# Lire un fichier texte
@app_modal.function(volumes={"/sandbox": volume})
def read_file(filename: str):
    path = f"/sandbox/{filename}"
    if not os.path.exists(path):
        return f"File '{filename}' not found."
    with open(path, "r") as f:
        return f.read()

# Copier un projet local dans la sandbox
@app_modal.function(volumes={"/sandbox": volume})
def copy_project(local_path: str, remote_path: str = "/sandbox/project"):
    import shutil
    if os.path.exists(remote_path):
        shutil.rmtree(remote_path)
    shutil.copytree(local_path, remote_path)
    return f"Project copied to {remote_path}"

# Lancer le projet Next.js
@app_modal.function(volumes={"/sandbox": volume}, timeout=1800)
def start_nextjs():
    import subprocess
    os.chdir("/sandbox/project")
    subprocess.run(["npm", "install"], check=True)
    subprocess.run(["npm", "run", "dev"], check=True)
    # Dans start_nextjs()
    subprocess.Popen(["npm", "run", "start", "--", "-p", "3000", "--hostname", "0.0.0.0"])

    return "Next.js started"

@app_modal.function(secrets=[modal.Secret.from_name("ngrok-token")], volumes={"/sandbox": volume},timeout=1800)
def start_nextjs_with_ngrok():
    import os
    import subprocess
    import time
    import requests

    os.chdir("/sandbox/project")

    # Installer ngrok v3 si pas présent
    if not os.path.exists("/usr/local/bin/ngrok"):
        subprocess.run([
            "wget",
            "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz",
            "-O", "/tmp/ngrok.tgz"
        ], check=True)
        subprocess.run(["tar", "-xvzf", "/tmp/ngrok.tgz", "-C", "/usr/local/bin"], check=True)

    # Lancer Next.js sur 0.0.0.0:3000
    subprocess.Popen(["npm", "run", "start", "--", "-p", "3000", "--hostname", "0.0.0.0"])

    # Récupérer le token injecté par Modal
    NGROK_TOKEN = os.getenv("NGROK_AUTHTOKEN")
    if NGROK_TOKEN:
        subprocess.run(["/usr/local/bin/ngrok", "config", "add-api-key", NGROK_TOKEN], check=True)

    # Lancer ngrok pour exposer le port 3000
    subprocess.Popen(["/usr/local/bin/ngrok", "http", "3000"])

    # Attendre que ngrok démarre
    time.sleep(5)

    # Lire l'URL publique depuis ngrok
    try:
        r = requests.get("http://localhost:4040/api/tunnels")
        tunnels = r.json().get("tunnels", [])
        public_url = tunnels[0]["public_url"] if tunnels else "ngrok tunnel not found"
    except Exception:
        public_url = "ngrok tunnel not found"

    return f"Next.js started! Access it via: {public_url}"



    
# Upload et décompression d’un zip Next.js
@app_modal.function(volumes={"/sandbox": volume})
def upload_and_extract_zip(file_bytes: bytes, filename: str, target_path: str = "/sandbox/project"):
    import shutil
    import zipfile

    # Supprimer le projet existant si nécessaire
    if os.path.exists(target_path):
        shutil.rmtree(target_path)

    # Écrire le zip dans la sandbox
    tmp_zip_path = f"/sandbox/{filename}"
    with open(tmp_zip_path, "wb") as f:
        f.write(file_bytes)

    # Décompresser le zip
    with zipfile.ZipFile(tmp_zip_path, "r") as zip_ref:
        zip_ref.extractall(target_path)

    # Supprimer le zip après extraction
    os.remove(tmp_zip_path)

    return f"Projet '{filename}' uploadé et décompressé dans {target_path}"

# Copier un projet prébuild dans la sandbox
@app_modal.function(volumes={"/sandbox": volume})
def copy_project_to_sandbox():
    import shutil
    local_path = "../prebuilt"
    remote_path = "/sandbox/project"
    if os.path.exists(remote_path):
        shutil.rmtree(remote_path)
    shutil.copytree(local_path, remote_path)
    return f"Project copied to {remote_path}"

# --------------------------
# Endpoints FastAPI
# --------------------------
class SandboxRequest(BaseModel):
    prompt: str

class FileRequest(BaseModel):
    filename: str
    content: str = None

# Prompt IA
@app.post("/sandbox/prompt")
def sandbox_prompt(data: SandboxRequest, user=Depends(get_current_user)):
    with app_modal.run():
        result = complete_text.remote(data.prompt)
    return {"response": result}

# Écrire un fichier texte
@app.post("/sandbox/write")
def sandbox_write_file(data: FileRequest, user=Depends(get_current_user)):
    if data.content is None:
        raise HTTPException(status_code=400, detail="Content is required")
    with app_modal.run():
        result = write_file.remote(data.filename, data.content)
    return {"message": result}

# Lire un fichier texte
@app.get("/sandbox/read")
def sandbox_read_file(filename: str, user=Depends(get_current_user)):
    with app_modal.run():
        result = read_file.remote(filename)
    return {"content": result}

# Upload d’un zip Next.js
@app.post("/sandbox/upload")
def upload_next_project(file: UploadFile):
    with app_modal.run():
        file_bytes = file.file.read()
        result = upload_and_extract_zip.remote(file_bytes, file.filename)
    return {"message": result}

# Copier projet prébuild
@app.post("/sandbox/project/copy")
def sandbox_copy_project(user=Depends(get_current_user)):
    with app_modal.run():
        result = copy_project_to_sandbox.remote()
    return {"message": result}

# Lancer Next.js
@app.post("/sandbox/project/run")
def sandbox_run_project(user=Depends(get_current_user)):
    with app_modal.run():
        result = start_nextjs.remote()
    return {"message": result}

@app.post("/sandbox/project/run/ngrok")
def sandbox_run_project(user=Depends(get_current_user)):
    with app_modal.run():
        url = start_nextjs_with_ngrok.remote()
    return {"ngrok_url": url}
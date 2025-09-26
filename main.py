import os
import json
import time
import requests
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
import modal
from dotenv import load_dotenv

load_dotenv()
JWT_SECRET = os.getenv("JWT_SECRET", "changeme")
JWT_ALGO = os.getenv("JWT_ALGO", "HS256")

Seconds = 60 #secondes

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return {"id": payload.get("sub"), "email": payload.get("email")}
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré")

# Modal App
app_modal = modal.App.lookup("codiris-sandbox-microservice", create_if_missing=True)

# Sandbox Image
sandbox_image = (
    modal.Image.debian_slim()
    .apt_install("git", "curl", "unzip", "wget", "python3", "python3-pip")
    .pip_install("requests")
    .run_commands([
           # Installer Node.js
        "curl -fsSL https://deb.nodesource.com/setup_20.x | bash -",
        "apt-get install -y nodejs",

        "git clone https://github.com/Mars-24/next.git /sandbox/project",

        "cd /sandbox/project && npm install"
    ])
)

def create_nextjs_sandbox(script: str = "dev") -> dict:

    try:
        # Lancer la sandbox avec le script npm choisi
        sandbox = modal.Sandbox.create(
            "npm", "--prefix", "/sandbox/project", "run", script,
            "--", "--port", "12345", "--hostname", "0.0.0.0",
            encrypted_ports=[12345],
            app=app_modal,
            image=sandbox_image,
            timeout=15 * Seconds,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur création sandbox: {str(e)}")

    # Attendre que l'app réponde
    for _ in range(60):
        try:
            r = requests.get(f"http://{sandbox.ip()}:12345")
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(1)

    # Récupérer le tunnel et construire une vraie URL HTTPS
    try:
        tunnel = sandbox.tunnels()[12345]
        url = f"https://{tunnel.host}:{tunnel.port}" if tunnel.port != 443 else f"https://{tunnel.host}"
        return {"sandbox": sandbox, "url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur récupération URL: {str(e)}")


@app.post("/sandbox/project/run")
def sandbox_run_project(user=Depends(get_current_user)):
    result = create_nextjs_sandbox()
    return {"url": result["url"]}

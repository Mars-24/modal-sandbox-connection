import os
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from jose import JWTError
from dotenv import load_dotenv
import modal

from database import Base, engine, get_db
from models import User
from schemas import UserCreate, UserRead, Token
from utils import hash_password, verify_password
from auth import create_access_token, verify_token

# -----------------------
# Charger les variables d'environnement
# -----------------------

load_dotenv()

os.environ["MODAL_API_TOKEN"] = os.getenv("MODAL_API_TOKEN")
modal_client = modal.Client.from_env()

# Créer les tables SQLAlchemy
Base.metadata.create_all(bind=engine)

# Initialiser FastAPI
app = FastAPI()

# -----------------------
# Configurer CORS
# -----------------------
origins = [
    "http://localhost:3000",  # front-end en dev
    "http://127.0.0.1:3000",
    # ajouter vos domaines front en prod ici, ex:
    # "https://mon-domaine.com"
]

image = (
    modal.Image.debian_slim()
    .pip_install_from_requirements("requirements.txt")
    .add_local_dir(".", remote_path="/root")
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OAuth2
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# -------------------
# ROUTE : création utilisateur
# -------------------
@app.post("/users/", response_model=UserRead)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email déjà utilisé")

    hashed_pwd = hash_password(user.password)
    new_user = User(name=user.name, email=user.email, hashed_password=hashed_pwd)

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

# -------------------
# ROUTE : login
# -------------------
@app.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou mot de passe incorrect")

    token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}

# -------------------
# ROUTE : info utilisateur connecté
# -------------------
@app.get("/users/me", response_model=UserRead)
def read_users_me(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = verify_token(token, credentials_exception)
    user_id = int(payload.get("sub"))
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user

# -------------------
# SANDBOX MODAL
# -------------------
app_modal = modal.App("sandbox-prompt-example",image=image)

@app_modal.function()
def run_prompt(prompt: str):
    # Ici logique réelle pour traiter le prompt
    return f"Réponse simulée pour : {prompt}"

    
@app.post("/sandbox/")
def sandbox_prompt(prompt: str, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = verify_token(token, credentials_exception)
    user_id = int(payload.get("sub"))
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception

    # Démarrer l'app Modal et appeler la fonction
    with app_modal.run():
        result = run_prompt.remote(prompt)

    return {"user": user.name, "response": result}
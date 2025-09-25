create your python env :
pip install -m venv venv

active your venv :
*on linux
source venv/bin/active
*on windows
venv\Scripts\Activate.ps1

Install all dependences :
pip install -r requirements.txt

set your MODAL_API_TOKEN in .env file

run your server with command :
unicorn main:app --reload

now you can access swagger documentation in url :
127.0.0.1:8000/docs  or http://localhost:8000/docs

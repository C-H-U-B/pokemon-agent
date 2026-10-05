# Image de l'API structurée : moteur SQL servi en HTTP, sans modèle.
FROM python:3.11-slim

WORKDIR /app

# PyTorch CPU seul : évite de télécharger les bibliothèques GPU.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY pyproject.toml constraints.txt ./
COPY src ./src
# Installation éditable : config.py déduit /app/data et /app/chroma_db de son propre emplacement.
RUN pip install --no-cache-dir -e . -c constraints.txt

EXPOSE 8000
# 0.0.0.0 : écouter sur toutes les interfaces du conteneur, sinon le port publié reste injoignable.
CMD ["uvicorn", "pokemon_rag.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

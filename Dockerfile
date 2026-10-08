# syntax=docker/dockerfile:1
# Deux images, une par cible :
#   api (par défaut)  moteur SQL servi en HTTP, sans modèle ni données   docker build .
#   demo              interface Web autonome, données et modèles inclus  docker build --target demo .
FROM python:3.11-slim AS base

WORKDIR /app

# PyTorch CPU seul : évite de télécharger les bibliothèques GPU.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY pyproject.toml constraints.txt ./
COPY src ./src
# Installation éditable : config.py déduit /app/data et /app/chroma_db de son propre emplacement.
RUN pip install --no-cache-dir -e . -c constraints.txt


# Démo pour un hébergeur sans volume (Cloud Run) : tout ce que compose.yaml monte est dans l'image.
# Le serveur de modèle reste extérieur : LLM_BASE_URL, LLM_MODEL et LLM_API_KEY sont fournis au
# déploiement, la clé par le gestionnaire de secrets de l'hébergeur, jamais par l'image.
FROM base AS demo

# Modèles de recherche (930 Mo), sous les noms que lit le code ; plus aucun accès à Hugging Face ensuite.
# ponytail: retéléchargés à chaque changement de src ; les placer avant COPY src si les builds se multiplient.
RUN python -c "from sentence_transformers import CrossEncoder, SentenceTransformer; from pokemon_rag.rag.retrieval import EMBEDDING_MODEL, RERANKER_MODEL; SentenceTransformer(EMBEDDING_MODEL); CrossEncoder(RERANKER_MODEL)"
ENV HF_HUB_OFFLINE=1

# Base et index de la release, vérifiés par leur somme : l'image ne dépend pas du disque de qui la construit.
# Changer de release : modifier l'étiquette et la somme sur la même ligne.
ADD --checksum=sha256:fc0b21ec28caa42ac038bc87e20f416b7fb41fc405aaab5f4241229510abe303     https://github.com/C-H-U-B/pokemon-agent/releases/download/v0.4.0/pokemon.db data/pokemon.db
ADD --checksum=sha256:4353571b46303e0eb9632fb7e797122a469c67f6a2b874581e730df05330342d     https://github.com/C-H-U-B/pokemon-agent/releases/download/v0.4.0/chroma_db.tar.gz /tmp/chroma_db.tar.gz
# ponytail: l'archive (112 Mo) reste dans la couche précédente ; une étape intermédiaire l'éviterait.
RUN tar -xzf /tmp/chroma_db.tar.gz -C /app && rm /tmp/chroma_db.tar.gz

# 0.0.0.0 : écouter sur toutes les interfaces du conteneur. Préchargement de la base documentaire
# dès l'ouverture de la page, pas pendant la première question.
ENV GRADIO_SERVER_NAME=0.0.0.0 POKEMON_RAG_PRELOAD=1
EXPOSE 7860
CMD ["python", "-m", "pokemon_rag.web.app"]


FROM base AS api

EXPOSE 8000
# 0.0.0.0 : écouter sur toutes les interfaces du conteneur, sinon le port publié reste injoignable.
CMD ["uvicorn", "pokemon_rag.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

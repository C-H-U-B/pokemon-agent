# syntax=docker/dockerfile:1
# Space Hugging Face (SDK Docker) : interface Web en simulation, réponses enregistrées rejouées,
# aucun appel au modèle ni aux outils. Ni modèles de recherche, ni index, ni base : sans base, les
# réponses s'affichent sans illustrations et le Guide garde ses exemples fixes (avertissements
# answer_images_failed et guide_names_failed au journal). Le code vient du dépôt public, à un commit fixé.
FROM python:3.11-slim

WORKDIR /app

# PyTorch CPU seul : sentence-transformers reste une dépendance du paquet, même inutilisée ici.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Publier une autre version : changer le commit (poussé sur GitHub).
ARG COMMIT=0fcd6e81bbfe1ee8a9438bddbe12494096e4bd75
ADD https://github.com/C-H-U-B/pokemon-agent/archive/${COMMIT}.tar.gz /tmp/src.tar.gz
RUN tar -xzf /tmp/src.tar.gz --strip-components=1 -C /app && rm /tmp/src.tar.gz \
    && pip install --no-cache-dir -e . -c constraints.txt

ENV GRADIO_SERVER_NAME=0.0.0.0 POKEMON_RAG_SIMULATION=1 HF_HUB_OFFLINE=1
EXPOSE 7860
CMD ["python", "-m", "pokemon_rag.web.app"]

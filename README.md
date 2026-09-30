# Pokémon RAG

Local question-answering system for Pokémon data combining structured queries and Retrieval-Augmented Generation (RAG).

The system uses two complementary data sources:

- **PokéAPI + custom Pokédex data** stored in a local SQLite database for structured queries.
- **Poképédia** pages indexed locally for documentary and open-ended questions.

The application automatically routes each question to the appropriate source.

## Architecture

Three query paths are available:

- **STRUCTURED** — queries the local SQLite database.
- **RAG** — retrieves relevant Poképédia content.
- **HYBRID** — combines structured data and Poképédia context.

Structured queries currently support:

- Pokémon evolutions and evolution conditions
- level-up moves
- machine moves
- move learning methods
- Pokémon types, national number and introduction generation
- signature and pseudo-signature moves

Custom profiles also support general presentations.

The RAG pipeline uses hybrid retrieval, section-aware retrieval and reranking before generating an answer.

## Stack

- Python
- LangGraph
- SQLite
- ChromaDB
- Sentence Transformers
- BM25
- CrossEncoder reranking
- LM Studio
- Local LLMs
- PokéAPI
- Poképédia

## Project structure

```text
pokemon-rag/
├── src/pokemon_rag/    # application Python
├── scripts/            # préparation des données, batch et analyse
├── tests/              # tests isolés et validations avec ressources locales
├── benchmarks/         # évaluations et références factuelles
├── docs/               # guides de contribution et de transmission
├── data/               # ressources locales, hors versionnement
└── DEVELOPMENT_FR.md   # historique de développement
```

Generated databases, Poképédia pages and vector indexes are not stored in the repository.

## Setup

Create and activate a Python environment, then install the dependencies:

```bash
pip install -r requirements.txt
pip install -e .
```

LM Studio must be running locally with the models expected by the application.

## Build the data

These commands prepare or rebuild local resources; skip them when the data already exists. Read [the scripts guide (French)](scripts/README.md) before running them.

Download the PokéAPI data:

```bash
python scripts/pokeapi/download_pokeapi.py
```

Build the PokéAPI database:

```bash
python scripts/pokeapi/build_pokeapi_db.py
```

Build the unified Pokémon database:

```bash
python scripts/pokeapi/build_pokemon_db.py
```

Download and clean the Poképédia corpus:

```bash
python scripts/pokepedia/download.py
python scripts/pokepedia/clean.py
```

Build the RAG index:

```bash
python scripts/pokepedia/ingest.py
```

## Run

Start LM Studio, load the required local models, then run:

```bash
python -m pokemon_rag.graph.graph
```

## Tests

Tests are located in:

```text
tests/
```

They cover the PokéAPI database, mappings, evolutions, move queries and the structured query engine.

## Documentation

A separate document will describe the design decisions, development process, experiments and benchmark results.
## Contributor guides

See [documentation navigation](docs/README.md) and [test prerequisites](tests/README.md). These contributor guides are maintained in French.

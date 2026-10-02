# Validation déterministe des corrections structurées — 2 octobre 2026

Aucun appel Qwen, LM Studio ou autre LLM réel. Les parcours ADK utilisent un
modèle simulé, avec MCP et SQLite réels. La campagne E2E existante et ses
résultats n'ont pas été remplacés. Aucun commit ni push.

## Régressions principales

Commande exécutée :

```powershell
conda run -n langgraph-agent python -m pytest tests/unit/test_explicit_pokemon_constraints.py tests/unit/test_stat_ranking_constraints.py tests/unit/test_adk_tool_guard.py tests/unit/test_adk_context_budget.py tests/unit/test_structured_e2e_reporting.py tests/unit/test_mcp_constraint_preservation.py tests/integration/test_explicit_pokemon_and_movepool.py tests/integration/test_pokemon_moves.py tests/integration/test_machine_moves_default_version.py tests/integration/test_adk_stat_rankings.py tests/integration/test_adk_mcp_toolset.py tests/integration/test_mcp_server.py tests/integration/test_pokedex_search_movepool.py -q -p no:cacheprovider --tb=short --basetemp=.pytest_tmp_structured_final
```

Résultat : **311 réussis**, 104 avertissements SDK, 47,36 s.
La première exécution du même ensemble, avec
`--basetemp=.pytest_tmp_structured_regressions`, avait donné 307 réussis et
1 échec : les CT de Gouroutan restaient tronquées. La projection des objets
d'items français et des numéros redondants a été corrigée avant la reprise.

## Vérifications ciblées exécutées

Toutes les lignes ci-dessous utilisent exactement ce préfixe et ces options :

```text
conda run -n langgraph-agent python -m pytest <sélection> -q -p no:cacheprovider --tb=short --basetemp=<répertoire>
```

Les chemins abrégés U et I signifient respectivement `tests/unit/` et
`tests/integration/`. Les résultats ne s'additionnent pas : des tests sont
réexécutés après modification.

| Sélection | Répertoire | Résultat |
| --- | --- | --- |
| U/test_explicit_pokemon_constraints.py U/test_adk_tool_guard.py I/test_explicit_pokemon_and_movepool.py I/test_machine_moves_default_version.py I/test_pokemon_moves.py | .pytest_tmp_constraints_latest | 67 réussis |
| U/test_adk_context_budget.py U/test_structured_e2e_reporting.py I/test_adk_stat_rankings.py I/test_adk_mcp_toolset.py | .pytest_tmp_presentation_constraints | 41 réussis |
| U/test_explicit_pokemon_constraints.py U/test_mcp_constraint_preservation.py U/test_adk_context_budget.py U/test_structured_e2e_reporting.py I/test_adk_stat_rankings.py | .pytest_tmp_final_presentation | 81 réussis |
| U/test_adk_context_budget.py U/test_structured_e2e_reporting.py I/test_adk_mcp_toolset.py | .pytest_tmp_structured_contracts_final | 39 réussis |
| U/test_structured_e2e_reporting.py I/test_adk_stat_rankings.py::test_e2e_recorder_separates_proposal_execution_raw_mcp_and_adk_projection | .pytest_tmp_e2e_effective_args | 15 réussis |
| U/test_explicit_pokemon_constraints.py U/test_structured_e2e_reporting.py U/test_adk_tool_guard.py | .pytest_tmp_explicit_targets_final | 52 réussis |
| U/test_explicit_pokemon_constraints.py U/test_adk_context_budget.py U/test_structured_e2e_reporting.py I/test_adk_stat_rankings.py | .pytest_tmp_last_constraints | 63 réussis |
| U/test_structured_e2e_reporting.py | .pytest_tmp_reporting_alias_final | 14 réussis |
| U/test_structured_e2e_reporting.py | .pytest_tmp_reporting_resolved_move | 15 réussis |

La dernière vérification couvre aussi l'alias anglais d'une capacité dont
l'identité française est confirmée par le résultat MCP.

`git -c core.safecrlf=false diff --check` a également été exécuté.
La suite complète non auditée n'a pas été lancée pour éviter tout appel LLM.

## Mesures de contexte sans modèle

Reconstruction locale depuis les réponses du rapport, les déclarations MCP
et les instructions courantes, puis application du budget ADK. Le script
temporaire `.context_measure.py` a été exécuté par
`conda run -n langgraph-agent python .context_measure.py`, puis supprimé.

| Cas | Réponse avant/après projection, octets UTF-8 | Contexte avant/après, octets UTF-8 |
| --- | --- | --- |
| 9 légendaires génération 4 | 2 415 → 604 | 12 590 → 2 929 |
| 8 Pokémon Eau/Vol | 2 189 → 575 | 12 328 → 2 864 |

Aucune abstention locale pour ces reconstructions. Les budgets n'ont pas
augmenté. Ces mesures ne sont ni une consommation de tokens Qwen ni une
validation de sa réponse finale.

## Relance manuelle uniquement

```powershell
conda run -n langgraph-agent python -m pytest tests/long/test_adk_structured_database_e2e.py -q -s -p no:cacheprovider
```

Préconditions : données locales disponibles et serveur LM Studio/Qwen
configuré comme pour la campagne précédente. Le rapport conserve la
progression initiale et les sorties Markdown/JSONL, et sépare proposition,
guard, arguments effectifs, réponse MCP brute, projection ADK et réponse finale.

Les tests factuels détectent notamment des niveaux numériques non sourcés,
des valeurs de classement manquantes ou erronées et des libellés anglais
ajoutés. Ils ne constituent pas une validation exhaustive de toute phrase
en langue naturelle. Talents et formes par défaut des trois exceptions
restent hors périmètre. Aucune migration ou reconstruction de base.

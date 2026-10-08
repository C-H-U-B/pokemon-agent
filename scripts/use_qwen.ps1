# Ramène ce terminal PowerShell au modèle local (Qwen sur LM Studio), après scripts/use_gemini.ps1 :
#   . scripts/use_qwen.ps1          (avec le point : les variables changent dans le terminal)
# Les variables sont supprimées, pas réécrites : config.py retombe sur ses valeurs par défaut.
Remove-Item Env:LLM_BASE_URL, Env:LLM_MODEL, Env:LLM_API_KEY, Env:LLM_MAX_OUTPUT_TOKENS -ErrorAction SilentlyContinue
Write-Host "Modèle : valeurs par défaut de config.py (Qwen sur LM Studio)"

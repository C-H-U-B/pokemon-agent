# Pointe ce terminal PowerShell vers le modèle de la démo (Gemini), pour l'interface ou un script :
#   . scripts/use_gemini.ps1        (avec le point : les variables restent dans le terminal)
# La clé n'est pas dans le dépôt. Elle est lue dans la variable utilisateur GEMINI_API_KEY,
# à enregistrer une seule fois :
#   [Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "<clé>", "User")
$key = [Environment]::GetEnvironmentVariable("GEMINI_API_KEY", "User")
if (-not $key) {
    Write-Error "GEMINI_API_KEY absente : enregistrez-la une fois (commande en tête de ce fichier)."
    return
}
$env:LLM_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
$env:LLM_MODEL = "gemini-3.8-flash"
$env:LLM_API_KEY = $key
# Gemini compte sa réflexion dans la limite de sortie : 1 024 coupe les réponses longues.
$env:LLM_MAX_OUTPUT_TOKENS = "2048"
# agent.py laisse une variable OPENAI_* déjà présente l'emporter sur LLM_BASE_URL.
Remove-Item Env:OPENAI_API_BASE, Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
Write-Host "Modèle : $env:LLM_MODEL ($env:LLM_BASE_URL)"

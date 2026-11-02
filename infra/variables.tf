variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "image_tag" {
  type    = string
  default = "latest"
}

variable "champion_model" {
  description = "Bedrock EU cross-region inference profile of the frontier model"
  type        = string
  default     = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "challenger_base_url" {
  description = "OpenAI-compatible base URL of the Modal vLLM server, e.g. https://<workspace>--claimdesk-serve.modal.run/v1"
  type        = string
  default     = ""
}

variable "challenger_api_key" {
  type      = string
  sensitive = true
  default   = "unset"
}

variable "budget_email" {
  type = string
}

variable "github_repo" {
  type    = string
  default = "Attila-Hartmann/claimdesk"
}

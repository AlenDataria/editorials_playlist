variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "eu-west-1"
}

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "editorials-playlist"
}

variable "timezone" {
  description = "Timezone for cron schedules"
  type        = string
  default     = "UTC"
}

variable "docker_image" {
  description = "Docker image for the ECS task (optional, defaults to managed ECR repo latest tag)"
  type        = string
  default     = ""
}

variable "container_name" {
  description = "Name of the container in the ECS task"
  type        = string
  default     = "editorials-playlist-container"
}

variable "ecs_task_cpu" {
  description = "CPU units for the ECS task (256 = 0.25 vCPU)"
  type        = number
  default     = 256
}

variable "ecs_task_memory" {
  description = "Memory for the ECS task in MB (minimum for 256 CPU is 512 MB)"
  type        = number
  default     = 512
}

variable "container_environment_vars" {
  description = "Non-sensitive environment variables for the container"
  type = list(object({
    name  = string
    value = string
  }))
  default = []
}

variable "secrets_manager_arn" {
  description = "ARN of AWS Secrets Manager secret containing the DB_* values"
  type        = string
  default     = ""
}

variable "github_repository" {
  description = "GitHub repository (owner/name) allowed to push images via OIDC"
  type        = string
  default     = "datariaengineers/editorials_playlist"
}

variable "create_github_oidc_provider" {
  description = "Create the GitHub Actions OIDC provider. Set to false if the AWS account already has one (only one per account is allowed) and set github_oidc_provider_arn."
  type        = bool
  default     = false
}

variable "github_oidc_provider_arn" {
  description = "ARN of an existing GitHub Actions OIDC provider, used when create_github_oidc_provider is false"
  type        = string
  default     = ""
}

variable "secrets_manager_keys" {
  description = "Secret keys to inject from AWS Secrets Manager as environment variables. Names must match what the app reads (src/db.py)."
  type        = list(string)
  default = [
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
  ]
}

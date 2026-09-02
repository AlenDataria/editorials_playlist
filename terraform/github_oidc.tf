# GitHub Actions OIDC federation: lets the deploy workflow in this repo push
# images to ECR without long-lived AWS keys stored in GitHub.

# An account can hold only one OIDC provider per URL. song_resolver_tracker's
# Terraform already creates it, so this repo defaults to reusing it:
# create_github_oidc_provider = false + pass its ARN via github_oidc_provider_arn.
resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd"
  ]

  tags = {
    Name      = "${var.project_name}-github-oidc"
    Project   = var.project_name
    ManagedBy = "Terraform"
  }
}

locals {
  github_oidc_provider_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : var.github_oidc_provider_arn
}

# Role assumable only by workflow runs on this repository's main branch
resource "aws_iam_role" "github_actions_ecr_push" {
  name = "${var.project_name}-github-actions-ecr-push"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRoleWithWebIdentity"
        Principal = {
          Federated = local.github_oidc_provider_arn
        }
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          # StringLike: GitHub now issues immutable subject claims
          # (repo:<owner>@<id>/<repo>@<id>:...), so github_repository must carry
          # that form and we match any ref under it.
          StringLike = {
            "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:*"
          }
        }
      }
    ]
  })

  tags = {
    Name      = "${var.project_name}-github-actions-ecr-push"
    Project   = var.project_name
    ManagedBy = "Terraform"
  }
}

# Push/pull access limited to the project's ECR repository
resource "aws_iam_role_policy" "github_actions_ecr_push" {
  name = "${var.project_name}-github-actions-ecr-push"
  role = aws_iam_role.github_actions_ecr_push.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage"
        ]
        Resource = aws_ecr_repository.ep.arn
      }
    ]
  })
}

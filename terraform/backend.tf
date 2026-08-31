terraform {
  backend "s3" {
    bucket  = "editorials-playlist-tfstate"
    key     = "terraform/terraform.tfstate"
    region  = "eu-west-1"
    encrypt = true
  }
}

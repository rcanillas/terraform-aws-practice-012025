variable "python_runtime" {
  type        = string
  description = "Name of the python version to use at runtime"
  default     = "python3.12"
}

variable "python_version" {
  type        = string
  description = "Name of the python version to use at runtime"
  default     = "3.12"
}

variable "python_module" {
  type        = string
  description = "Name of the module for the lambda function"
  default     = "lambda_function"
}
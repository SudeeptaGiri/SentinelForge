"""Jinja2 renderer for Terraform HCL & Cloud Build YAML.

Description: Wraps Jinja2 to render `.tf.j2` / `.yaml.j2` templates from
             `templates/` into concrete Terraform/CI-CD files.
Need: The Infra Agent must generate real IaC/pipeline files from parameters
      decided upstream (cost/scaling plan) without duplicating templating
      logic in every agent.
Motive: Keep template rendering (variable substitution, escaping) in one
        tested utility used by all IaC/CI-CD generation.
"""

from jinja2 import Environment, FileSystemLoader


def render_template(template_path: str, context: dict) -> str:
    """Renders a Jinja2 template file with the given context dict."""
    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template(template_path)
    return template.render(**context)

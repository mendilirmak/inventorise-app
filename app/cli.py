"""`flask create-user <username>`: the only way to create or update a user.

Prompts for the password (typed twice, hidden). Scripts can pass
`--password`, but note it is then visible in the process list and shell
history; piping it on stdin is safer (see README).
"""

import click

from .auth import UserError, set_user_password


@click.command("create-user")
@click.argument("username")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def create_user(username, password):
    """Create USERNAME, or reset its password if it already exists."""
    try:
        created = set_user_password(username, password)
    except UserError as exc:
        raise click.ClickException(str(exc)) from None
    click.echo(f"User '{username}' {'created' if created else 'password updated'}.")


def register(app):
    app.cli.add_command(create_user)

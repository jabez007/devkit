# Read with ast by the validator to resolve model_example; never imported.
from odoo import models


class Example(models.Model):
    _name = "example"
    _description = "Example"

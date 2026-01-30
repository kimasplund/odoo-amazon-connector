# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

from . import models
from . import wizards
from . import controllers


def post_init_hook(env):
    """
    Post-installation hook.
    - Initialize default configurations
    - Ensure marketplace data integrity
    """
    # Ensure all marketplace records have correct sequence
    marketplaces = env['amazon.marketplace'].search([])
    for idx, marketplace in enumerate(marketplaces.sorted('name'), start=1):
        marketplace.write({'sequence': idx * 10})


def uninstall_hook(env):
    """
    Cleanup hook on module uninstall.
    - Remove scheduled actions
    - Clean up any temporary data
    """
    # Clean up cron jobs
    cron_jobs = env['ir.cron'].search([
        ('cron_name', 'ilike', 'amazon')
    ])
    cron_jobs.unlink()

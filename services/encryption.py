# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

import base64
import logging
from typing import Any, Union, Optional

from cryptography.fernet import Fernet
from odoo import api, tools

_logger = logging.getLogger(__name__)

CONFIG_PARAM_KEY = 'amazon_connector.encryption_key'


def _get_fernet(env: Any) -> Fernet:
    """
    Get or create the Fernet encryption instance.
    The key is stored in ir.config_parameter.
    """
    param_model = env['ir.config_parameter'].sudo()
    key = param_model.get_param(CONFIG_PARAM_KEY)

    if not key:
        # Generate a new key if not exists
        key = Fernet.generate_key().decode('utf-8')
        param_model.set_param(CONFIG_PARAM_KEY, key)
        _logger.info("Generated new encryption key for Amazon Connector")

    try:
        return Fernet(key.encode('utf-8'))
    except Exception as e:
        _logger.error("Failed to initialize Fernet with stored key: %s", e)
        # Fallback to a temporary key to avoid crashing, but log error
        # In production this should be handled more gracefully
        return Fernet(Fernet.generate_key())


def encrypt(env: Any, data: Union[str, bytes]) -> Union[str, bool]:
    """
    Encrypt string data.

    Args:
        env: Odoo Environment
        data: String to encrypt

    Returns:
        Encrypted string (base64 encoded) or False if data is empty
    """
    if not data:
        return False

    try:
        f = _get_fernet(env)
        data_bytes: bytes
        if isinstance(data, str):
            data_bytes = data.encode('utf-8')
        else:
            data_bytes = data

        encrypted = f.encrypt(data_bytes)
        return encrypted.decode('utf-8')
    except Exception as e:
        _logger.error("Encryption failed: %s", e)
        return False


def decrypt(env: Any, data: Union[str, bytes]) -> Union[str, bool]:
    """
    Decrypt string data.

    Args:
        env: Odoo Environment
        data: Encrypted string

    Returns:
        Decrypted string or False if data is empty/invalid
    """
    if not data:
        return False

    try:
        f = _get_fernet(env)
        data_bytes: bytes
        if isinstance(data, str):
            data_bytes = data.encode('utf-8')
        else:
            data_bytes = data

        decrypted = f.decrypt(data_bytes)
        return decrypted.decode('utf-8')
    except Exception as e:
        # Don't log the actual data or too much info to avoid leaking info
        _logger.warning("Decryption failed: %s", str(e))
        return False

# -*- coding: utf-8 -*-
# Part of Odoo 18 Amazon Connector
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)

from odoo import api, fields, models, _


class AmazonProductCategory(models.Model):
    """Amazon Product Category (Browse Node).
    
    Represents Amazon's product category hierarchy (browse nodes).
    Used for proper product categorization and attribute mapping.
    """
    _name = 'amazon.product.category'
    _description = 'Amazon Product Category'
    _parent_name = 'parent_id'
    _parent_store = True
    _order = 'complete_name'
    _rec_name = 'complete_name'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------
    name = fields.Char(
        string='Category Name',
        required=True,
        index=True,
        translate=True,
        help='Amazon product category name',
    )
    complete_name = fields.Char(
        string='Complete Name',
        compute='_compute_complete_name',
        recursive=True,
        store=True,
        help='Full category path',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    
    # Amazon Specific
    browse_node_id = fields.Char(
        string='Browse Node ID',
        required=True,
        index=True,
        help='Amazon Browse Node ID',
    )
    marketplace_id = fields.Many2one(
        comodel_name='amazon.marketplace',
        string='Marketplace',
        required=True,
        ondelete='cascade',
        help='Marketplace this category belongs to',
    )
    
    # Hierarchy
    parent_id = fields.Many2one(
        comodel_name='amazon.product.category',
        string='Parent Category',
        index=True,
        ondelete='cascade',
    )
    parent_path = fields.Char(
        string='Parent Path',
        index=True,
    )
    child_ids = fields.One2many(
        comodel_name='amazon.product.category',
        inverse_name='parent_id',
        string='Child Categories',
    )
    child_count = fields.Integer(
        string='# Children',
        compute='_compute_child_count',
    )
    
    # Category Properties
    is_leaf = fields.Boolean(
        string='Is Leaf',
        compute='_compute_is_leaf',
        store=True,
        help='Whether this is a leaf category (no children)',
    )
    level = fields.Integer(
        string='Level',
        compute='_compute_level',
        store=True,
        help='Depth in the category hierarchy',
    )
    
    # Mapping
    odoo_category_id = fields.Many2one(
        comodel_name='product.category',
        string='Odoo Category',
        help='Mapped Odoo product category',
    )
    
    # Product Type Info
    product_type = fields.Char(
        string='Product Type',
        help='Amazon product type for this category',
    )
    item_type = fields.Char(
        string='Item Type',
        help='Amazon item type keyword',
    )

    # -------------------------------------------------------------------------
    # CONSTRAINTS
    # -------------------------------------------------------------------------
    _sql_constraints = [
        (
            'browse_node_marketplace_unique',
            'UNIQUE(browse_node_id, marketplace_id)',
            'Browse Node ID must be unique per marketplace!',
        ),
    ]

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------
    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for category in self:
            if category.parent_id:
                category.complete_name = f'{category.parent_id.complete_name} / {category.name}'
            else:
                category.complete_name = category.name

    @api.depends('child_ids')
    def _compute_child_count(self):
        for category in self:
            category.child_count = len(category.child_ids)

    @api.depends('child_ids')
    def _compute_is_leaf(self):
        for category in self:
            category.is_leaf = not bool(category.child_ids)

    @api.depends('parent_path')
    def _compute_level(self):
        for category in self:
            if category.parent_path:
                category.level = category.parent_path.count('/') - 1
            else:
                category.level = 0

    # -------------------------------------------------------------------------
    # BUSINESS METHODS
    # -------------------------------------------------------------------------
    def name_get(self):
        """Return display name with browse node ID for clarity."""
        result = []
        for category in self:
            name = f'{category.complete_name} [{category.browse_node_id}]'
            result.append((category.id, name))
        return result

    @api.model
    def get_or_create(self, browse_node_id, marketplace_id, name, parent_id=None):
        """Get existing category or create new one.
        
        Args:
            browse_node_id: Amazon browse node ID
            marketplace_id: Marketplace record ID
            name: Category name
            parent_id: Parent category ID (optional)
            
        Returns:
            amazon.product.category record
        """
        category = self.search([
            ('browse_node_id', '=', browse_node_id),
            ('marketplace_id', '=', marketplace_id),
        ], limit=1)
        
        if not category:
            category = self.create({
                'browse_node_id': browse_node_id,
                'marketplace_id': marketplace_id,
                'name': name,
                'parent_id': parent_id,
            })
        
        return category

    def action_view_products(self):
        """View products in this category."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Products in %s') % self.name,
            'res_model': 'amazon.product.listing',
            'view_mode': 'tree,form',
            'domain': [('amazon_category_id', '=', self.id)],
            'context': {'default_amazon_category_id': self.id},
        }

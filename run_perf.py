import time
import sys
import unittest
from unittest.mock import MagicMock

class MockEnv:
    def __init__(self):
        self.products = []
        self.calls = 0

    def __getitem__(self, key):
        if key == 'product.product':
            return self
        return self

    def search(self, domain, limit=None):
        self.calls += 1
        if len(domain) > 0 and domain[0][1] == 'in':
            skus = domain[0][2]
            res = []
            for p in self.products:
                if p.default_code in skus:
                    res.append(p)
            return res
        return []

    def create(self, vals):
        self.calls += 1
        if isinstance(vals, dict):
            vals = [vals]
        new_prods = []
        for val in vals:
            p = MagicMock()
            p.id = len(self.products) + 1
            p.default_code = val.get('default_code')
            p.name = val.get('name')
            self.products.append(p)
            new_prods.append(p)
        return new_prods

class MockLine:
    def __init__(self, sku, title, price):
        self.seller_sku = sku
        self.title = title
        self.item_price = price
        self.product_id = None

class MockOrderLineIds:
    def __init__(self, lines):
        self.lines = lines

    def filtered(self, func):
        return MockOrderLineIds([l for l in self.lines if func(l)])

    def mapped(self, attr):
        return [getattr(l, attr) for l in self.lines]

    def __iter__(self):
        return iter(self.lines)

class MockOrder:
    def __init__(self, lines):
        self.line_ids = MockOrderLineIds(lines)

class OrderSyncWizard:
    def __init__(self):
        self.env = MockEnv()

    def _create_sale_order_perf(self, amazon_order):
        # Pre-fetch and create placeholder products in batch to avoid N+1 queries
        lines_missing_products = amazon_order.line_ids.filtered(lambda l: not l.product_id and l.seller_sku)
        sku_to_product = {}

        if lines_missing_products.lines:
            Product = self.env['product.product']
            skus = list(set(lines_missing_products.mapped('seller_sku')))

            # Batch search existing
            existing_products = Product.search([('default_code', 'in', skus)])
            for p in existing_products:
                if p.default_code:
                    sku_to_product[p.default_code] = p

            # Batch create missing
            create_vals = []
            seen_skus = set(sku_to_product.keys())

            for line in lines_missing_products:
                if line.seller_sku not in seen_skus:
                    create_vals.append({
                        'name': line.title or f'Amazon Product {line.seller_sku}',
                        'default_code': line.seller_sku,
                        'type': 'consu',
                        'list_price': line.item_price,
                    })
                    seen_skus.add(line.seller_sku)

            if create_vals:
                new_products = Product.create(create_vals)
                for p in new_products:
                    if p.default_code:
                        sku_to_product[p.default_code] = p

        # Create sale order lines
        for line in amazon_order.line_ids:
            product = line.product_id
            if not product:
                # Use pre-fetched/created placeholder product
                if line.seller_sku and line.seller_sku in sku_to_product:
                    product = sku_to_product[line.seller_sku]
                else:
                    # Fallback for edge cases (e.g., missing seller_sku)
                    pass

# Test
wizard = OrderSyncWizard()
lines = [MockLine(f"SKU-{i}", f"Title {i}", 10.0) for i in range(1000)]
order = MockOrder(lines)

start = time.time()
wizard._create_sale_order_perf(order)
end = time.time()

print(f"Optimized Time: {end - start:.4f}s")
print(f"Env calls: {wizard.env.calls}")

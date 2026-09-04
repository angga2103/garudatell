from app.core.logger import logger

def register(events):

    events.on(
        "product.updated",
        lambda p: logger.info(f"PRODUCT UPDATED : {p.sku_code}")
    )

    events.on(
        "product.created",
        lambda p: logger.info(f"PRODUCT CREATED : {p.sku_code}")
    )

    events.on(
        "margin.changed",
        lambda c: logger.info(f"MARGIN UPDATED : {c}")
    )

    events.on(
        "config.changed",
        lambda k: logger.info(f"CONFIG UPDATED : {k}")
    )

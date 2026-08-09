"""Small synthetic dataset used by tests and the first demo."""

from .models import AttributeValue, Evidence, Product, ProductVersion


def valve_version(version_id: str, pressure: int, source: str) -> ProductVersion:
    evidence = Evidence(source_name=source, source_type="datasheet", page=2, excerpt=f"Pressure rating: {pressure} WOG")
    return ProductVersion(
        version_id=version_id,
        product_id="valve-001",
        attributes=(
            AttributeValue("size", 1, "in", (evidence,)),
            AttributeValue("pressure_rating", pressure, "WOG", (evidence,)),
            AttributeValue("temperature_range", "-20 to 180", "°C", (evidence,)),
            AttributeValue("material", "brass", None, (evidence,)),
            AttributeValue("connection_type", "female NPT", None, (evidence,)),
        ),
    )


def sample_product() -> Product:
    return Product(
        product_id="valve-001",
        sku="VALVE-001",
        name="Brass Ball Valve",
        category="industrial_valve",
        versions=(valve_version("v1", 600, "valve-datasheet-v1.pdf"),),
    )


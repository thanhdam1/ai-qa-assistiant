from typing import Dict, Any, List, Optional
from faker import Faker
from pydantic import BaseModel, Field

fake = Faker()

class SyntheticDataset(BaseModel):
    endpoint_path: str
    method: str
    valid_payloads: List[Dict[str, Any]] = Field(default_factory=list)
    boundary_payloads: List[Dict[str, Any]] = Field(default_factory=list)
    invalid_payloads: List[Dict[str, Any]] = Field(default_factory=list)
    security_payloads: List[Dict[str, Any]] = Field(default_factory=list)

class SyntheticDataGenerator:
    """
    Synthesizes realistic and edge-case test fixtures
    grounded strictly on OpenAPI schemas and properties.
    """

    @classmethod
    def generate_for_schema(cls, schema: Dict[str, Any], endpoint_path: str = "/api/resource", method: str = "POST") -> SyntheticDataset:
        properties = schema.get("properties", {})
        required_fields = schema.get("required", [])

        # 1. Valid Payload
        valid_sample = cls._generate_valid_sample(properties)
        valid_sample_2 = cls._generate_valid_sample(properties)

        # 2. Boundary Payload
        boundary_sample = cls._generate_boundary_sample(properties)

        # 3. Invalid Payload (missing required fields & wrong types)
        invalid_sample_1 = dict(valid_sample)
        if required_fields:
            # Drop first required field
            invalid_sample_1.pop(required_fields[0], None)
        else:
            invalid_sample_1["_invalid_key"] = None

        invalid_sample_2 = cls._generate_invalid_type_sample(properties)

        # 4. Security Payload (SQLi, XSS)
        security_sample_1 = cls._generate_security_sample(properties, "sqli")
        security_sample_2 = cls._generate_security_sample(properties, "xss")

        return SyntheticDataset(
            endpoint_path=endpoint_path,
            method=method,
            valid_payloads=[valid_sample, valid_sample_2],
            boundary_payloads=[boundary_sample],
            invalid_payloads=[invalid_sample_1, invalid_sample_2],
            security_payloads=[security_sample_1, security_sample_2]
        )

    @classmethod
    def _generate_valid_sample(cls, properties: Dict[str, Any]) -> Dict[str, Any]:
        sample = {}
        for prop_name, prop_spec in properties.items():
            p_type = prop_spec.get("type", "string")
            p_format = prop_spec.get("format", "")
            enum_values = prop_spec.get("enum")

            if enum_values:
                sample[prop_name] = enum_values[0]
            elif p_type == "string":
                if p_format == "email" or "email" in prop_name.lower():
                    sample[prop_name] = fake.email()
                elif p_format == "uuid" or "id" in prop_name.lower():
                    sample[prop_name] = fake.uuid4()
                elif p_format == "date" or "date" in prop_name.lower():
                    sample[prop_name] = fake.date()
                elif "name" in prop_name.lower():
                    sample[prop_name] = fake.name()
                elif "phone" in prop_name.lower():
                    sample[prop_name] = fake.phone_number()
                elif "address" in prop_name.lower():
                    sample[prop_name] = fake.address()
                else:
                    sample[prop_name] = fake.word()
            elif p_type in ["integer", "number"]:
                min_val = prop_spec.get("minimum", 1)
                max_val = prop_spec.get("maximum", 1000)
                sample[prop_name] = fake.random_int(min=int(min_val), max=int(max_val))
            elif p_type == "boolean":
                sample[prop_name] = True
            elif p_type == "array":
                sample[prop_name] = [fake.word()]
            else:
                sample[prop_name] = fake.word()
        return sample

    @classmethod
    def _generate_boundary_sample(cls, properties: Dict[str, Any]) -> Dict[str, Any]:
        sample = {}
        for prop_name, prop_spec in properties.items():
            p_type = prop_spec.get("type", "string")
            if p_type in ["integer", "number"]:
                # Boundary value: minimum or maximum
                if "minimum" in prop_spec:
                    sample[prop_name] = prop_spec["minimum"]
                elif "maximum" in prop_spec:
                    sample[prop_name] = prop_spec["maximum"]
                else:
                    sample[prop_name] = 0
            elif p_type == "string":
                # Max length or single char or empty string
                max_len = prop_spec.get("maxLength", 255)
                sample[prop_name] = "A" * min(max_len, 255)
            elif p_type == "boolean":
                sample[prop_name] = False
            else:
                sample[prop_name] = ""
        return sample

    @classmethod
    def _generate_invalid_type_sample(cls, properties: Dict[str, Any]) -> Dict[str, Any]:
        sample = {}
        for prop_name, prop_spec in properties.items():
            p_type = prop_spec.get("type", "string")
            if p_type in ["integer", "number"]:
                sample[prop_name] = "not_a_number_string"
            elif p_type == "boolean":
                sample[prop_name] = 9999
            elif p_type == "string":
                sample[prop_name] = {"nested_object_instead_of_string": True}
            else:
                sample[prop_name] = None
        return sample

    @classmethod
    def _generate_security_sample(cls, properties: Dict[str, Any], attack_type: str) -> Dict[str, Any]:
        sample = {}
        payload = "' OR '1'='1' --" if attack_type == "sqli" else "<script>alert('XSS')</script>"
        for prop_name, prop_spec in properties.items():
            p_type = prop_spec.get("type", "string")
            if p_type == "string":
                sample[prop_name] = payload
            elif p_type in ["integer", "number"]:
                sample[prop_name] = -1
            else:
                sample[prop_name] = None
        return sample

"""CYBER SWARM TRADING OS - AICL Protocol Engine

AI Inter-Agent Compact Communication Language (AICL)
Canonical format:
    @ACT SRC>DST | CTX | OBJ | CON | DATA | OUT | ST | NEXT
"""
import re
from typing import Any
from pydantic import BaseModel, Field

class AICLMessage(BaseModel):
    action: str = Field(description="Action verb, e.g. ANL, SET, GET, VAL, ACK, SIG")
    source: str = Field(description="Source agent ID, e.g. TIDAL, NORO, ORC")
    destination: str = Field(description="Destination agent ID, e.g. ORC, ALL, VESKA")
    context: str | None = None
    objective: str | None = None
    constraints: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    raw_data: str | None = None
    output_format: str | None = None
    state: str = "RDY"
    next_action: str | None = None
    raw: str = ""

    def encode(self) -> str:
        """Serializes the structured AICL message into canonical compact string format."""
        header = f"@{self.action.upper()} {self.source.upper()}>{self.destination.upper()}"
        parts = []
        if self.context:
            parts.append(f"CTX={self.context}")
        if self.objective:
            parts.append(f"OBJ={self.objective}")
        if self.constraints:
            parts.append(f"CON={self.constraints}")

        # Serialize data dict if present
        if self.data:
            data_items = [f"{k}:{v}" for k, v in self.data.items()]
            parts.append(f"DATA={','.join(data_items)}")
        elif self.raw_data:
            parts.append(f"DATA={self.raw_data}")

        if self.output_format:
            parts.append(f"OUT={self.output_format}")
        parts.append(f"ST={self.state}")
        if self.next_action:
            parts.append(f"NEXT={self.next_action}")

        return f"{header}|{'|'.join(parts)}"

    @classmethod
    def decode(cls, text: str) -> "AICLMessage":
        """Parses a canonical compact string into an AICLMessage instance."""
        text = text.strip()
        if not text:
            raise ValueError("AICL text cannot be empty")

        # Split header and segments
        if "|" in text:
            header_part, *segment_parts = text.split("|")
        else:
            header_part = text
            segment_parts = []

        # Parse header: @ACT SRC>DST
        header_part = header_part.strip()
        match = re.match(r"^@?([A-Za-z0-9_-]+)\s+([A-Za-z0-9_-]+)>([A-Za-z0-9_-]+)", header_part)
        if not match:
            # Fallback simple header parsing
            action = "SET"
            source = "ORC"
            destination = "ALL"
        else:
            action = match.group(1).upper()
            source = match.group(2).upper()
            destination = match.group(3).upper()

        msg = cls(
            action=action,
            source=source,
            destination=destination,
            raw=text
        )

        for segment in segment_parts:
            segment = segment.strip()
            if not segment:
                continue

            if "=" in segment:
                key, val = segment.split("=", 1)
                key = key.upper().strip()
                val = val.strip()

                if key == "CTX":
                    msg.context = val
                elif key == "OBJ":
                    msg.objective = val
                elif key == "CON":
                    msg.constraints = val
                elif key == "OUT":
                    msg.output_format = val
                elif key == "ST":
                    msg.state = val
                elif key == "NEXT":
                    msg.next_action = val
                elif key == "DATA":
                    msg.raw_data = val
                    data_dict = {}
                    for item in val.split(","):
                        if ":" in item:
                            dk, dv = item.split(":", 1)
                            # Convert number types where applicable
                            dv_raw = dv.strip()
                            parsed_val: Any = dv_raw
                            try:
                                parsed_val = float(dv_raw) if "." in dv_raw else int(dv_raw)
                            except ValueError:
                                parsed_val = dv_raw
                            data_dict[dk.strip().lower()] = parsed_val
                        else:
                            data_dict[item.strip().lower()] = True
                    msg.data = data_dict
            else:
                # Bare key/flag
                msg.data[segment.lower()] = True

        return msg

    def apply_delta(self, delta_str: str) -> None:
        """Applies delta changes: Δ:+KEY=VAL;~KEY=VAL;-KEY"""
        delta_body = delta_str.replace("Δ:", "").replace("delta:", "")
        for instruction in delta_body.split(";"):
            instruction = instruction.strip()
            if not instruction:
                continue
            op = instruction[0]
            rest = instruction[1:]
            if op == "+" and "=" in rest:  # Add
                k, v = rest.split("=", 1)
                self.data[k.strip().lower()] = v.strip()
            elif op == "-":  # Remove
                self.data.pop(rest.strip().lower(), None)
            elif op == "~" and "=" in rest:  # Modify
                k, v = rest.split("=", 1)
                self.data[k.strip().lower()] = v.strip()

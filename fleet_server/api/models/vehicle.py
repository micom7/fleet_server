from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class VehicleOut(BaseModel):
    id:           UUID
    name:         str
    vpn_ip:       str
    api_port:     int
    last_seen_at: datetime | None
    sync_status:  str


class VehicleCreate(BaseModel):
    name:     str
    vpn_ip:   str
    api_port: int = 8001


class AssignVehicleBody(BaseModel):
    user_id: UUID


class AlarmOut(BaseModel):
    id:           int
    alarm_id:     int
    channel_id:   int | None
    severity:     str | None
    message:      str
    triggered_at: datetime
    resolved_at:  datetime | None


class ChannelOut(BaseModel):
    channel_id: int
    name:       str
    unit:       str | None
    min_value:  float | None
    max_value:  float | None
    synced_at:  datetime

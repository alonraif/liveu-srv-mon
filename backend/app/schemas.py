from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    username: str
    role: str
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=256)


class StatusCurrentResponse(BaseModel):
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    temperature_c: float | None
    network_interface: str | None
    rx_mbps: float | None
    tx_mbps: float | None
    liveu_service_status: str
    disks: list[dict[str, Any]]
    os_version: str
    kernel_version: str
    server_version: str | None


class StatusHistoryResponse(BaseModel):
    samples: list[dict[str, Any]]


class NetworkResponse(BaseModel):
    internal_ip: str | None
    public_ip: str | None
    link_status: str
    ssh_port_22: str


class IdentityResponse(BaseModel):
    base_unique_id: str | None
    server_license: str | None
    server_type: str


class GatherLogsResponse(BaseModel):
    bundle_id: str
    filename: str


class AdminPasswordConfirm(BaseModel):
    password: str


class RebootRequest(BaseModel):
    password: str
    confirmation: str


class SpeedtestResultResponse(BaseModel):
    timestamp: str
    download_mbps: float
    upload_mbps: float
    ping_ms: float
    server_name: str
    server_sponsor: str
    server_country: str
    server_host: str
    public_ip: str


class ApiError(BaseModel):
    detail: str

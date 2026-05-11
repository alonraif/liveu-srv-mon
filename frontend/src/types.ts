export type AuthState = {
  username: string;
  role: string;
  must_change_password: boolean;
};

export type StatusCurrent = {
  timestamp: string;
  cpu_percent: number;
  memory_percent: number;
  temperature_c: number | null;
  network_interface: string | null;
  rx_mbps: number | null;
  tx_mbps: number | null;
  liveu_service_status: string;
  disks: Array<{
    filesystem: string;
    size: string;
    used: string;
    avail: string;
    use_percent: string;
    mounted_on: string;
  }>;
  os_version: string;
  kernel_version: string;
  server_version: string | null;
};

export type StatusHistory = {
  samples: Array<{
    timestamp: string;
    cpu_percent: number;
    memory_percent: number;
    temperature_c: number | null;
    network_interface: string | null;
    rx_mbps: number | null;
    tx_mbps: number | null;
  }>;
};

export type NetworkInfo = {
  internal_ip: string | null;
  public_ip: string | null;
  link_status: string;
  ssh_port_22: string;
};

export type Identity = {
  base_unique_id: string | null;
  server_license: string | null;
  server_type: string;
};

export type AuditEntry = {
  timestamp: string;
  username: string;
  action: string;
  details: string;
  remote_ip: string | null;
};

export type SpeedtestResult = {
  timestamp: string;
  download_mbps: number;
  upload_mbps: number;
  ping_ms: number;
  server_name: string;
  server_sponsor: string;
  server_country: string;
  server_host: string;
  public_ip: string;
};

export type AdvertisedIpStatus = {
  local_ip_options: Array<{
    interface: string;
    ip: string;
    label: string;
  }>;
  file_exists: boolean;
  configured_ip: string | null;
  selected_mode: string;
  selected_ip: string | null;
};

import os
import logging
import structlog
from dataclasses import dataclass, field


@dataclass
class HuggingFaceConfig:
    token: str | None
    base_url: str
    sort_field: str
    sort_direction: int
    page_size: int


@dataclass
class RateLimitingConfig:
    max_requests_per_second: int
    max_concurrent_requests: int
    max_retries: int
    backoff_base_seconds: float
    backoff_max_seconds: float


@dataclass
class PhaseGatingConfig:
    phase2_start_threshold_pct: int
    phase3_start_threshold_pct: int


@dataclass
class StorageConfig:
    duckdb_path: str
    jsonl_archive_dir: str


@dataclass
class CheckpointConfig:
    dir: str
    save_every_n_pages: int


@dataclass
class LoggingConfig:
    level: str
    file: str
    progress_every_n_models: int


@dataclass
class MonitoringConfig:
    enabled: bool
    pushgateway_host: str
    pushgateway_port: int
    loki_host: str
    loki_port: int
    job_name: str
    instance_name: str
    push_interval_seconds: int


@dataclass
class Config:
    environment: str
    huggingface: HuggingFaceConfig
    rate_limiting: RateLimitingConfig
    phase_gating: PhaseGatingConfig
    storage: StorageConfig
    checkpoint: CheckpointConfig
    logging: LoggingConfig
    monitoring: MonitoringConfig
    max_items: int | None = None

    @classmethod
    def from_yaml(cls, path: str, max_items: int | None = None) -> 'Config':
        import yaml
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        return cls(
            environment=data['environment'],
            huggingface=HuggingFaceConfig(
                token=os.path.expandvars(data['huggingface']['token']),
                base_url=data['huggingface']['base_url'],
                sort_field=data['huggingface']['sort_field'],
                sort_direction=data['huggingface']['sort_direction'],
                page_size=data['huggingface']['page_size'],
            ),
            rate_limiting=RateLimitingConfig(
                max_requests_per_second=data['rate_limiting']['max_requests_per_second'],
                max_concurrent_requests=data['rate_limiting']['max_concurrent_requests'],
                max_retries=data['rate_limiting']['max_retries'],
                backoff_base_seconds=data['rate_limiting']['backoff_base_seconds'],
                backoff_max_seconds=data['rate_limiting']['backoff_max_seconds'],
            ),
            phase_gating=PhaseGatingConfig(
                phase2_start_threshold_pct=data['phase_gating']['phase2_start_threshold_pct'],
                phase3_start_threshold_pct=data['phase_gating']['phase3_start_threshold_pct'],
            ),
            storage=StorageConfig(
                duckdb_path=data['storage']['duckdb_path'],
                jsonl_archive_dir=data['storage']['jsonl_archive_dir'],
            ),
            checkpoint=CheckpointConfig(
                dir=data['checkpoint']['dir'],
                save_every_n_pages=data['checkpoint']['save_every_n_pages'],
            ),
            logging=LoggingConfig(
                level=data['logging']['level'],
                file=data['logging']['file'],
                progress_every_n_models=data['logging']['progress_every_n_models'],
            ),
            monitoring=MonitoringConfig(
                enabled=data['monitoring']['enabled'],
                pushgateway_host=data['monitoring']['pushgateway_host'],
                pushgateway_port=data['monitoring']['pushgateway_port'],
                loki_host=data['monitoring']['loki_host'],
                loki_port=data['monitoring']['loki_port'],
                job_name=data['monitoring']['job_name'],
                instance_name=data['monitoring']['instance_name'],
                push_interval_seconds=data['monitoring']['push_interval_seconds'],
            ),
            max_items=max_items,
        )


def setup_logging(config: Config) -> None:
    logging.basicConfig(
        level=getattr(logging, config.logging.level.upper()),
        format='%(message)s',
        handlers=[
            logging.FileHandler(config.logging.file),
            logging.StreamHandler(),
        ],
    )
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

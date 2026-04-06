"""Current ORM baseline

Revision ID: 1ff2d78b663d
Revises:
Create Date: 2025-08-05 16:12:49.159120

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1ff2d78b663d"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("member_id", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("role", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_login", sa.DateTime(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("member_id"),
    )
    op.create_index(op.f("ix_members_id"), "members", ["id"], unique=False)
    op.create_index(op.f("ix_members_member_id"), "members", ["member_id"], unique=False)
    op.create_index(op.f("ix_members_email"), "members", ["email"], unique=False)

    op.create_table(
        "any_cloud_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cache_key", sa.String(length=255), nullable=False),
        sa.Column("request_signature", sa.Text(), nullable=False),
        sa.Column("cached_response", sa.JSON(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cache_key"),
    )
    op.create_index(op.f("ix_any_cloud_cache_id"), "any_cloud_cache", ["id"], unique=False)
    op.create_index("idx_any_cloud_cache_expires", "any_cloud_cache", ["expires_at"], unique=False)
    op.create_index("idx_any_cloud_cache_active", "any_cloud_cache", ["is_active"], unique=False)
    op.create_index("idx_any_cloud_cache_created", "any_cloud_cache", ["created_at"], unique=False)

    op.create_table(
        "any_cloud_data",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_path", sa.String(length=500), nullable=False),
        sa.Column("request_method", sa.String(length=10), nullable=False),
        sa.Column("request_params", sa.JSON(), nullable=True),
        sa.Column("request_body", sa.JSON(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_data", sa.JSON(), nullable=False),
        sa.Column("response_headers", sa.JSON(), nullable=True),
        sa.Column("member_id", sa.String(length=50), nullable=False),
        sa.Column("user_role", sa.String(length=50), nullable=True),
        sa.Column("user_name", sa.String(length=100), nullable=True),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column("is_cached", sa.Boolean(), nullable=True),
        sa.Column("cache_key", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_any_cloud_data_id"), "any_cloud_data", ["id"], unique=False)
    op.create_index("idx_any_cloud_data_path_method", "any_cloud_data", ["request_path", "request_method"], unique=False)
    op.create_index("idx_any_cloud_data_member_created", "any_cloud_data", ["member_id", "created_at"], unique=False)
    op.create_index("idx_any_cloud_data_status", "any_cloud_data", ["response_status"], unique=False)
    op.create_index("idx_any_cloud_data_category", "any_cloud_data", ["category"], unique=False)
    op.create_index("idx_any_cloud_data_cache_key", "any_cloud_data", ["cache_key"], unique=False)

    op.create_table(
        "datasets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("surro_dataset_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", sa.String(length=50), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_datasets_id"), "datasets", ["id"], unique=False)
    op.create_index(op.f("ix_datasets_surro_dataset_id"), "datasets", ["surro_dataset_id"], unique=False)
    op.create_index(op.f("ix_datasets_created_by"), "datasets", ["created_by"], unique=False)
    op.create_index("idx_datasets_member_active", "datasets", ["created_by", "is_active", "deleted_at"], unique=False)
    op.create_index("idx_datasets_surro_member", "datasets", ["surro_dataset_id", "created_by"], unique=False)
    op.create_index("idx_datasets_created_member", "datasets", ["created_by", "created_at"], unique=False)
    op.create_index(
        "idx_datasets_unique_mapping",
        "datasets",
        ["surro_dataset_id", "created_by"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "hub_connections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hub_name", sa.String(length=100), nullable=False),
        sa.Column("hub_url", sa.String(length=500), nullable=False),
        sa.Column("hub_type", sa.String(length=50), nullable=False),
        sa.Column("auth_type", sa.String(length=50), nullable=False),
        sa.Column("auth_config", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("connection_timeout", sa.Integer(), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=True),
        sa.Column("supports_search", sa.Boolean(), nullable=True),
        sa.Column("supports_download", sa.Boolean(), nullable=True),
        sa.Column("supports_upload", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.String(length=50), nullable=False),
        sa.Column("updated_by", sa.String(length=50), nullable=True),
        sa.Column("metadatas", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_hub_connections_id"), "hub_connections", ["id"], unique=False)
    op.create_index("idx_hub_connections_name_active", "hub_connections", ["hub_name", "is_active"], unique=False)
    op.create_index("idx_hub_connections_default", "hub_connections", ["is_default"], unique=False)

    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("collection_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("surro_knowledge_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["members.member_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_bases_id"), "knowledge_bases", ["id"], unique=False)
    op.create_index(op.f("ix_knowledge_bases_surro_knowledge_id"), "knowledge_bases", ["surro_knowledge_id"], unique=False)
    op.create_index("idx_knowledge_bases_surro_id", "knowledge_bases", ["surro_knowledge_id"], unique=True)

    op.create_table(
        "lite_model_data",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_path", sa.String(length=500), nullable=True),
        sa.Column("request_method", sa.String(length=10), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("member_id", sa.String(length=50), nullable=True),
        sa.Column("cache_key", sa.String(length=255), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lite_model_data_id"), "lite_model_data", ["id"], unique=False)
    op.create_index("idx_lite_model_data_expires", "lite_model_data", ["expires_at"], unique=False)
    op.create_index("idx_lite_model_data_active", "lite_model_data", ["is_active"], unique=False)
    op.create_index("idx_lite_model_data_created", "lite_model_data", ["created_at"], unique=False)
    op.create_index("idx_lite_model_data_member_created", "lite_model_data", ["member_id", "created_at"], unique=False)

    op.create_table(
        "models",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("surro_model_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", sa.String(length=50), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_catalog", sa.Boolean(), nullable=False),
        sa.Column("metadatas", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_models_id"), "models", ["id"], unique=False)
    op.create_index(op.f("ix_models_surro_model_id"), "models", ["surro_model_id"], unique=False)
    op.create_index(op.f("ix_models_created_by"), "models", ["created_by"], unique=False)
    op.create_index("idx_models_member_active", "models", ["created_by", "is_active", "deleted_at"], unique=False)
    op.create_index("idx_models_surro_member", "models", ["surro_model_id", "created_by"], unique=False)
    op.create_index("idx_models_created_member", "models", ["created_by", "created_at"], unique=False)
    op.create_index(
        "idx_models_unique_mapping",
        "models",
        ["surro_model_id", "created_by"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "prompts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("prompt_variable", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("surro_prompt_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["members.member_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_prompts_id"), "prompts", ["id"], unique=False)
    op.create_index(op.f("ix_prompts_surro_prompt_id"), "prompts", ["surro_prompt_id"], unique=False)
    op.create_index("idx_prompts_surro_prompt_id", "prompts", ["surro_prompt_id"], unique=True)

    op.create_table(
        "services",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("surro_service_id", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["members.member_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_services_id"), "services", ["id"], unique=False)
    op.create_index(op.f("ix_services_surro_service_id"), "services", ["surro_service_id"], unique=False)
    op.create_index("idx_services_surro_service_id", "services", ["surro_service_id"], unique=True)

    op.create_table(
        "workflows",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("surro_workflow_id", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["members.member_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workflows_id"), "workflows", ["id"], unique=False)
    op.create_index(op.f("ix_workflows_surro_workflow_id"), "workflows", ["surro_workflow_id"], unique=False)
    op.create_index("idx_workflows_surro_id", "workflows", ["surro_workflow_id"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_workflows_surro_id", table_name="workflows")
    op.drop_index(op.f("ix_workflows_surro_workflow_id"), table_name="workflows")
    op.drop_index(op.f("ix_workflows_id"), table_name="workflows")
    op.drop_table("workflows")

    op.drop_index("idx_services_surro_service_id", table_name="services")
    op.drop_index(op.f("ix_services_surro_service_id"), table_name="services")
    op.drop_index(op.f("ix_services_id"), table_name="services")
    op.drop_table("services")

    op.drop_index("idx_prompts_surro_prompt_id", table_name="prompts")
    op.drop_index(op.f("ix_prompts_surro_prompt_id"), table_name="prompts")
    op.drop_index(op.f("ix_prompts_id"), table_name="prompts")
    op.drop_table("prompts")

    op.drop_index("idx_models_unique_mapping", table_name="models", postgresql_where=sa.text("deleted_at IS NULL"))
    op.drop_index("idx_models_created_member", table_name="models")
    op.drop_index("idx_models_surro_member", table_name="models")
    op.drop_index("idx_models_member_active", table_name="models")
    op.drop_index(op.f("ix_models_created_by"), table_name="models")
    op.drop_index(op.f("ix_models_surro_model_id"), table_name="models")
    op.drop_index(op.f("ix_models_id"), table_name="models")
    op.drop_table("models")

    op.drop_index("idx_lite_model_data_member_created", table_name="lite_model_data")
    op.drop_index("idx_lite_model_data_created", table_name="lite_model_data")
    op.drop_index("idx_lite_model_data_active", table_name="lite_model_data")
    op.drop_index("idx_lite_model_data_expires", table_name="lite_model_data")
    op.drop_index(op.f("ix_lite_model_data_id"), table_name="lite_model_data")
    op.drop_table("lite_model_data")

    op.drop_index("idx_knowledge_bases_surro_id", table_name="knowledge_bases")
    op.drop_index(op.f("ix_knowledge_bases_surro_knowledge_id"), table_name="knowledge_bases")
    op.drop_index(op.f("ix_knowledge_bases_id"), table_name="knowledge_bases")
    op.drop_table("knowledge_bases")

    op.drop_index("idx_hub_connections_default", table_name="hub_connections")
    op.drop_index("idx_hub_connections_name_active", table_name="hub_connections")
    op.drop_index(op.f("ix_hub_connections_id"), table_name="hub_connections")
    op.drop_table("hub_connections")

    op.drop_index("idx_datasets_unique_mapping", table_name="datasets", postgresql_where=sa.text("deleted_at IS NULL"))
    op.drop_index("idx_datasets_created_member", table_name="datasets")
    op.drop_index("idx_datasets_surro_member", table_name="datasets")
    op.drop_index("idx_datasets_member_active", table_name="datasets")
    op.drop_index(op.f("ix_datasets_created_by"), table_name="datasets")
    op.drop_index(op.f("ix_datasets_surro_dataset_id"), table_name="datasets")
    op.drop_index(op.f("ix_datasets_id"), table_name="datasets")
    op.drop_table("datasets")

    op.drop_index("idx_any_cloud_data_cache_key", table_name="any_cloud_data")
    op.drop_index("idx_any_cloud_data_category", table_name="any_cloud_data")
    op.drop_index("idx_any_cloud_data_status", table_name="any_cloud_data")
    op.drop_index("idx_any_cloud_data_member_created", table_name="any_cloud_data")
    op.drop_index("idx_any_cloud_data_path_method", table_name="any_cloud_data")
    op.drop_index(op.f("ix_any_cloud_data_id"), table_name="any_cloud_data")
    op.drop_table("any_cloud_data")

    op.drop_index("idx_any_cloud_cache_created", table_name="any_cloud_cache")
    op.drop_index("idx_any_cloud_cache_active", table_name="any_cloud_cache")
    op.drop_index("idx_any_cloud_cache_expires", table_name="any_cloud_cache")
    op.drop_index(op.f("ix_any_cloud_cache_id"), table_name="any_cloud_cache")
    op.drop_table("any_cloud_cache")

    op.drop_index(op.f("ix_members_email"), table_name="members")
    op.drop_index(op.f("ix_members_member_id"), table_name="members")
    op.drop_index(op.f("ix_members_id"), table_name="members")
    op.drop_table("members")

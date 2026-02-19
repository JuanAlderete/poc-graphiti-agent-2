from poc.config import config

# Re-export config to keep agent module consistent
# In a real scenario, this might be separate, but for POC we share the config.
settings = config

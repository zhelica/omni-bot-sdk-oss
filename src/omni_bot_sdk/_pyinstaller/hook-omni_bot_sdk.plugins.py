"""
PyInstaller hook to collect plugin entry points for omni_bot_sdk.

This ensures that importlib.metadata.entry_points(group="omni_bot.plugins")
works correctly in the frozen (packaged) environment.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Collect all plugin submodules so PyInstaller includes them
hiddenimports = collect_submodules("omni_bot_sdk.plugins")

# Add explicit hidden imports for all plugin classes referenced in entry points
hiddenimports += [
    "omni_bot_sdk.plugins.core.self_msg_plugin",
    "omni_bot_sdk.plugins.core.openai_bot_plugin",
    "omni_bot_sdk.plugins.core.scheduled_leader_quotes_plugin",
    "omni_bot_sdk.plugins.core.leader_quotes_phrases",
    "omni_bot_sdk.plugins.core.block_empty_room_plugin",
    "omni_bot_sdk.plugins.core.image_aes_plugin",
    "omni_bot_sdk.plugins.core.message_recall_plugin",
    "omni_bot_sdk.plugins.core.plugin_interface",
    "omni_bot_sdk.plugins.interface",
]

# Collect plugin data files (config, static assets, etc.)
datas = collect_data_files("omni_bot_sdk.plugins")

# This repository's mods, each built into build/<name>/ as the folder to copy to <game>\mods\<name>\. The rules are
# sadkmod's (sadkmod/mods.mk). The mods a lobby player needs (gamebridge, assetshare, billboards) are in lobby/mods.
#   make          every mod (builds sadkmod first)
#   make verify   checks every mod's patches against a DRM-free SADK.exe under Wine (SADK_EXE=<path>)
SADKMOD ?= ../sadkmod
include $(SADKMOD)/mods.mk

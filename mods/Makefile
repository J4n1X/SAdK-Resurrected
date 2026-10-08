# The repo's own mods, each built into build/<name>/ as the folder to copy to <game>\mods\<name>\.
#   make          every mod (builds sadkmod first)
#   make verify   checks every mod's patches against a DRM-free SADK.exe under Wine (SADK_EXE=<path>)
#   make test     assetshare's archive format under Wine
# A mod is a folder here with one or more .cpp files (and optionally files to ship next to mod.dll, e.g. .ini,
# and a data/ folder that is copied as is). A folder without .cpp files is a data-only mod: its data/ folder and
# its flag files (.client / .server / .lobby) are copied.
CXX = i686-w64-mingw32-g++
SADKMOD = ../sadkmod
include $(SADKMOD)/pch.mk
MAKEFLAGS += -j$(shell nproc)
CXXFLAGS = $(SADKMOD_CXXFLAGS) -I$(SADKMOD)/include -I$(SADKMOD)/build/include
LIB = $(SADKMOD)/build/libsadkmod.a
GENERATED = $(SADKMOD)/build/include/.generated
LIBS = $(LIB) -lkernel32 -ladvapi32 -lshell32 -luser32 -lws2_32
SADK_EXE ?= $(HOME)/sadk_game/bin/SADK.exe

MODS = $(patsubst %/,%,$(filter-out tests/ build/,$(wildcard */)))
CODE_MODS = $(foreach m,$(MODS),$(if $(wildcard $(m)/*.cpp),$(m)))
DATA_MODS = $(filter-out $(CODE_MODS),$(MODS))
DLLS = $(CODE_MODS:%=build/%/mod.dll)
SOURCES = $(foreach m,$(CODE_MODS),$(wildcard $(m)/*.cpp))
# Each source once for the mod.dll and once for verify_mods.exe (SADKMOD_NO_ENTRY: no exports, entry.hpp), both from
# sadkmod's precompiled header; -MMD keeps track of the headers each one includes.
OBJ_DIR = build/obj
VERIFY_OBJ_DIR = build/obj-verify

all: $(DLLS) $(DATA_MODS:%=data-%)

# A mod without code: its data folder and its flag files (.client / .server / .lobby name what it changes).
data-%: FORCE
	@rm -rf build/$* && mkdir -p build/$*
	@if [ -d $*/data ]; then cp -r $*/data build/$*/; fi
	@for f in $*/.client $*/.server $*/.lobby; do if [ -e $$f ]; then cp $$f build/$*/; fi; done

$(LIB) $(GENERATED) $(SADKMOD_PCH_GCH): FORCE
	$(MAKE) -C $(SADKMOD)

$(OBJ_DIR)/%.o: %.cpp $(SADKMOD_PCH_GCH)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(SADKMOD_PCH_FLAGS) -MMD -MP -c -o $@ $<

$(VERIFY_OBJ_DIR)/%.o: %.cpp $(SADKMOD_PCH_GCH)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(SADKMOD_PCH_FLAGS) -DSADKMOD_NO_ENTRY -MMD -MP -c -o $@ $<

-include $(SOURCES:%.cpp=$(OBJ_DIR)/%.d) $(SOURCES:%.cpp=$(VERIFY_OBJ_DIR)/%.d)

.SECONDEXPANSION:
build/%/mod.dll: $$(patsubst %.cpp,$(OBJ_DIR)/%.o,$$(wildcard %/*.cpp)) $(LIB)
	@mkdir -p $(dir $@)
	$(CXX) -shared -s -static-libgcc -static-libstdc++ -o $@ $(filter %.o,$^) $(LIBS)
	@for f in $(wildcard $*/*.ini $*/*.txt); do cp $$f $(dir $@); done
	@rm -rf $(dir $@)data
	@if [ -d $*/data ]; then cp -r $*/data $(dir $@); fi

build/verify_mods.exe: $(VERIFY_OBJ_DIR)/tests/verify_mods.o $(SOURCES:%.cpp=$(VERIFY_OBJ_DIR)/%.o) $(LIB)
	@mkdir -p build
	$(CXX) -static -o $@ $(filter %.o,$^) $(LIBS)

verify: build/verify_mods.exe
	WINEDEBUG=-all wine build/verify_mods.exe "$(SADK_EXE)"

build/test_archive.exe: tests/test_archive.cpp assetshare/archive.cpp assetshare/archive.hpp
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -static -o $@ tests/test_archive.cpp assetshare/archive.cpp

test: build/test_archive.exe
	WINEDEBUG=-all wine build/test_archive.exe

clean:
	rm -rf build

FORCE:

.PHONY: all verify test clean FORCE

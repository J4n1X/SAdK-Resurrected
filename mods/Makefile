# The repo's own mods, each built into build/<name>/ as the folder to copy to <game>\mods\<name>\.
#   make          every mod (builds sadkmod first)
#   make verify   checks every mod's patches against a DRM-free SADK.exe under Wine (SADK_EXE=<path>)
# A mod is a folder here with one or more .cpp files (and optionally files to ship next to mod.dll, e.g. .ini,
# and a data/ folder that is copied as is).
CXX = i686-w64-mingw32-g++
SADKMOD = ../sadkmod
CXXFLAGS = -std=c++23 -O2 -Wall -Wextra -fno-exceptions -fno-rtti -I$(SADKMOD)/include -I$(SADKMOD)/build/include
LIB = $(SADKMOD)/build/libsadkmod.a
GENERATED = $(SADKMOD)/build/include/.generated
LIBS = $(LIB) -lkernel32 -ladvapi32 -lshell32 -luser32
SADK_EXE ?= $(HOME)/sadk_game/bin/SADK.exe

MODS = $(patsubst %/,%,$(filter-out tests/ build/,$(wildcard */)))
DLLS = $(MODS:%=build/%/mod.dll)

all: $(DLLS)

$(LIB) $(GENERATED): FORCE
	$(MAKE) -C $(SADKMOD)

.SECONDEXPANSION:
build/%/mod.dll: $$(wildcard %/*.cpp) $(LIB) $(GENERATED)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -shared -s -static-libgcc -static-libstdc++ -o $@ $(filter %.cpp,$^) $(LIBS)
	@for f in $(wildcard $*/*.ini $*/*.txt); do cp $$f $(dir $@); done
	@if [ -d $*/data ]; then cp -r $*/data $(dir $@); fi

build/verify_mods.exe: tests/verify_mods.cpp $(wildcard */*.cpp) $(LIB) $(GENERATED)
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -DSADKMOD_NO_ENTRY -static -o $@ tests/verify_mods.cpp $(foreach m,$(MODS),$(wildcard $(m)/*.cpp)) $(LIBS)

verify: build/verify_mods.exe
	WINEDEBUG=-all wine build/verify_mods.exe "$(SADK_EXE)"

clean:
	rm -rf build

FORCE:

.PHONY: all verify clean FORCE

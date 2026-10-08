CC = i686-w64-mingw32-gcc
WINDRES = i686-w64-mingw32-windres
SHIM = ../wsock32_shim/wsock32.dll
MOD_BILLBOARDS = ../../mods/build/billboards/mod.dll

SAdK-ServerConfig.exe: main.c res.o
	$(CC) -O2 -s -mwindows -static-libgcc -o $@ main.c res.o -lcomctl32 -lshlwapi -lshell32 -lole32 -ladvapi32

MODS = $(MOD_BILLBOARDS) ../../mods/build/gamebridge/mod.dll ../../mods/build/assetshare/mod.dll
MOD_INIS = ../../mods/billboards/billboards.ini ../../mods/gamebridge/gamebridge.ini ../../mods/assetshare/assetshare.ini

res.o: serverconfig.rc resource.h serverconfig.manifest sadk.ico $(SHIM) $(MODS) $(MOD_INIS)
	$(WINDRES) -O coff -o $@ serverconfig.rc

$(SHIM): FORCE
	$(MAKE) -C ../wsock32_shim

$(MODS): FORCE
	$(MAKE) -C ../../mods

FORCE:
.PHONY: FORCE

clean:
	rm -f SAdK-ServerConfig.exe res.o

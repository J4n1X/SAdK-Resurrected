CC = i686-w64-mingw32-gcc
WINDRES = i686-w64-mingw32-windres
SHIM = ../wsock32_shim/wsock32.dll

SAdK-ServerConfig.exe: main.c res.o
	$(CC) -O2 -s -mwindows -static-libgcc -o $@ main.c res.o -lcomctl32 -lshlwapi -lshell32 -lole32 -ladvapi32

res.o: serverconfig.rc resource.h serverconfig.manifest sadk.ico $(SHIM)
	$(WINDRES) -O coff -o $@ serverconfig.rc

$(SHIM):
	$(MAKE) -C ../wsock32_shim

clean:
	rm -f SAdK-ServerConfig.exe res.o

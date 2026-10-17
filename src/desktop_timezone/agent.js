'use strict';
const config = __CONFIG__;
const zone = Memory.alloc(config.dynamic.length);
zone.writeByteArray(config.dynamic);
const iana = Memory.allocUtf16String(config.iana);
const kernel = Process.getModuleByName('kernel32.dll');
const symbol = name => kernel.findExportByName(name);
const native = (name, ret, args) => new NativeFunction(symbol(name), ret, args);
const utcNow = native('GetSystemTime', 'void', ['pointer']);
const toLocal = native('SystemTimeToTzSpecificLocalTimeEx', 'bool', ['pointer', 'pointer', 'pointer']);
const toUtc = native('TzSpecificLocalTimeToSystemTimeEx', 'bool', ['pointer', 'pointer', 'pointer']);
const toFile = native('SystemTimeToFileTime', 'bool', ['pointer', 'pointer']);
const fromFile = native('FileTimeToSystemTime', 'bool', ['pointer', 'pointer']);
const forYear = native('GetTimeZoneInformationForYear', 'bool', ['uint16', 'pointer', 'pointer']);
const hooks = new Set();

function attach(address, handlers) {
  if (!address || hooks.has(address.toString())) return;
  Interceptor.attach(address, handlers);
  hooks.add(address.toString());
}
function state() {
  if (zone.add(70).readU16() === 0 || zone.add(154).readU16() === 0) return 0;
  const utc = Memory.alloc(16), local = Memory.alloc(16), a = Memory.alloc(8), b = Memory.alloc(8);
  utcNow(utc);
  if (!toLocal(zone, utc, local) || !toFile(utc, a) || !toFile(local, b)) return 0;
  const bias = Math.round((Number(a.readU64()) - Number(b.readU64())) / 600000000);
  return bias === zone.readS32() + zone.add(168).readS32() ? 2 : 1;
}

attach(symbol('GetTimeZoneInformation'), {
  onEnter(args) { this.output = args[0]; },
  onLeave(retval) { if (!this.output.isNull()) { this.output.writeByteArray(config.dynamic.slice(0, 172)); retval.replace(state()); } }
});
attach(symbol('GetDynamicTimeZoneInformation'), {
  onEnter(args) { this.output = args[0]; },
  onLeave(retval) { if (!this.output.isNull()) { this.output.writeByteArray(config.dynamic); retval.replace(state()); } }
});
attach(symbol('GetTimeZoneInformationForYear'), {
  onEnter(args) { if (args[1].isNull()) args[1] = zone; }
});
attach(symbol('GetLocalTime'), {
  onEnter(args) { this.output = args[0]; },
  onLeave() { if (!this.output.isNull()) { const utc = Memory.alloc(16); utcNow(utc); toLocal(zone, utc, this.output); } }
});
for (const name of ['SystemTimeToTzSpecificLocalTimeEx', 'TzSpecificLocalTimeToSystemTimeEx']) {
  attach(symbol(name), { onEnter(args) { if (args[0].isNull()) args[0] = zone; } });
}
for (const name of ['SystemTimeToTzSpecificLocalTime', 'TzSpecificLocalTimeToSystemTime']) {
  attach(symbol(name), {
    onEnter(args) {
      if (args[0].isNull()) {
        this.tzi = Memory.alloc(172);
        const year = args[1].readU16();
        if (forYear(year, zone, this.tzi)) args[0] = this.tzi;
      }
    }
  });
}
for (const [name, converter] of [['FileTimeToLocalFileTime', toLocal], ['LocalFileTimeToFileTime', toUtc]]) {
  attach(symbol(name), {
    onEnter(args) {
      this.input = Memory.alloc(8);
      if (!args[0].isNull()) this.input.writeByteArray(args[0].readByteArray(8));
      this.output = args[1];
    },
    onLeave(retval) {
      const source = Memory.alloc(16), target = Memory.alloc(16);
      if (!this.input.isNull() && !this.output.isNull() && fromFile(this.input, source) && converter(zone, source, target)) {
        retval.replace(toFile(target, this.output));
      }
    }
  });
}

const icuModules = new Set();
const observer = Process.attachModuleObserver({
  onAdded(module) {
    if (!/^icu(in|uc)\d+\.dll$/i.test(module.name) || icuModules.has(module.name)) return;
    icuModules.add(module.name);
    for (const entry of module.enumerateExports()) {
      if (/^ucal_open(?:_\d+)?$/.test(entry.name)) {
        attach(entry.address, { onEnter(args) { if (args[0].isNull()) { args[0] = iana; args[1] = ptr(config.iana.length); } } });
      }
      if (/^ucal_getDefaultTimeZone(?:_\d+)?$/.test(entry.name)) {
        attach(entry.address, {
          onEnter(args) { this.output = args[0]; this.capacity = args[1].toInt32(); this.status = args[2]; },
          onLeave(retval) {
            if (!this.output.isNull() && this.capacity > config.iana.length) {
              this.output.writeUtf16String(config.iana);
              if (!this.status.isNull()) this.status.writeS32(0);
              retval.replace(config.iana.length);
            }
          }
        });
      }
    }
  }
});

rpc.exports = {
  probe() {
    const output = Memory.alloc(432), local = Memory.alloc(16), utc = Memory.alloc(16);
    const getZone = native('GetDynamicTimeZoneInformation', 'uint', ['pointer']);
    const getLocal = native('GetLocalTime', 'void', ['pointer']);
    getZone(output); getLocal(local); utcNow(utc);
    const parts = value => Array.from({ length: 8 }, (_, index) => value.add(index * 2).readU16());
    return { pid: Process.id, timeZone: output.add(172).readUtf16String(), bias: output.readS32(), local: parts(local), utc: parts(utc), hooks: hooks.size };
  }
};
Interceptor.flush();
send({ event: 'installed', pid: Process.id, timeZone: config.windows, hooks: hooks.size });

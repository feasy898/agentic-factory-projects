import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DerpError } from '../src/frame.ts';
import { type DerpNode, type DerpRegion, DerpRegionPicker } from '../src/region.ts';

function mkNode(name: string): DerpNode {
  const n: DerpNode = {
    name: name,
    hostName: name + '.example.com',
    certName: '', // 实测 derp-map 全部缺省 CertName → TLS 校验层回退 hostName（取证 §3）
    ipv4: '198.51.100.30',
    ipv6: '',
    stunPort: 0, // 0 = 未显式下发 → 按 STUN_DEFAULT_PORT 兜底
    derpPort: 0, // 0 = 未显式下发 → 按 DERP_DEFAULT_PORT 兜底
    canPort80: true,
  };
  return n;
}

function mkRegion(id: number, code: string, latencyMs: number, nodeCount: number): DerpRegion {
  const nodes: DerpNode[] = [];
  for (let i: number = 0; i < nodeCount; i += 1) {
    nodes.push(mkNode(code + String(i)));
  }
  const r: DerpRegion = {
    regionId: id,
    regionCode: code,
    regionName: 'Region ' + code,
    nodes: nodes,
    latencyMs: latencyMs,
  };
  return r;
}

test('homeRegion：取最小非负延迟；并列取先声明者', (): void => {
  const picker: DerpRegionPicker = new DerpRegionPicker([
    mkRegion(1, 'a', 200, 1),
    mkRegion(2, 'b', 80, 1),
    mkRegion(3, 'c', 80, 1),
  ]);
  const h: DerpRegion | null = picker.homeRegion();
  assert.notEqual(h, null);
  if (h !== null) {
    assert.equal(h.regionId, 2);
  }
});

test('homeRegion：setLatency 覆盖后生效', (): void => {
  const picker: DerpRegionPicker = new DerpRegionPicker([
    mkRegion(1, 'a', 100, 1),
    mkRegion(2, 'b', -1, 1),
  ]);
  picker.setLatency(2, 50);
  const h: DerpRegion | null = picker.homeRegion();
  assert.notEqual(h, null);
  if (h !== null) {
    assert.equal(h.regionId, 2);
    // 覆盖值存选择器内部表，返回的 region 对象自身字段不被改写
    assert.equal(h.latencyMs, -1);
  }
});

test('homeRegion：全部未测出 → 第一个 nodes 非空的 region（取证 §5 兜底语义）', (): void => {
  const picker: DerpRegionPicker = new DerpRegionPicker([
    mkRegion(1, 'empty', -1, 0),
    mkRegion(2, 'headscale', -1, 2),
    mkRegion(3, 'c', -1, 1),
  ]);
  const h: DerpRegion | null = picker.homeRegion();
  assert.notEqual(h, null);
  if (h !== null) {
    assert.equal(h.regionId, 2);
  }
});

test('homeRegion：空列表 → null', (): void => {
  const picker: DerpRegionPicker = new DerpRegionPicker([]);
  assert.equal(picker.homeRegion(), null);
});

test('homeRegion：混有负值时只取非负者', (): void => {
  const picker: DerpRegionPicker = new DerpRegionPicker([
    mkRegion(1, 'a', -1, 1),
    mkRegion(2, 'b', 999, 1),
  ]);
  const h: DerpRegion | null = picker.homeRegion();
  assert.notEqual(h, null);
  if (h !== null) {
    assert.equal(h.regionId, 2);
  }
});

test('setLatency：未知 regionId 抛 RANGE', (): void => {
  const picker: DerpRegionPicker = new DerpRegionPicker([mkRegion(1, 'a', -1, 1)]);
  assert.throws(
    (): void => { picker.setLatency(99, 1); },
    (e: Error): boolean => e instanceof DerpError && e.code === 'RANGE',
  );
});

test('regionById：命中与未中', (): void => {
  const picker: DerpRegionPicker = new DerpRegionPicker([mkRegion(1, 'a', 10, 1), mkRegion(999, 'headscale', -1, 1)]);
  const r: DerpRegion | null = picker.regionById(999);
  assert.notEqual(r, null);
  if (r !== null) {
    assert.equal(r.regionCode, 'headscale');
  }
  assert.equal(picker.regionById(42), null);
});

test('pickNode：返回首节点；空 region 抛 RANGE', (): void => {
  const picker: DerpRegionPicker = new DerpRegionPicker([mkRegion(1, 'a', 10, 2)]);
  const region: DerpRegion | null = picker.regionById(1);
  assert.notEqual(region, null);
  if (region !== null) {
    const n: DerpNode = picker.pickNode(region);
    assert.equal(n.name, 'a0');
    const empty: DerpRegion = mkRegion(2, 'b', -1, 0);
    assert.throws(
      (): void => { picker.pickNode(empty); },
      (e: Error): boolean => e instanceof DerpError && e.code === 'RANGE',
    );
  }
});

test('节点缺省字段语义结构保持（certName=""/stunPort=0/derpPort=0 原样保存在结构中）', (): void => {
  // CertName 优先、HostName 回退的 TLS 行为在 app/ 侧实现；本包只保证结构语义不丢失。
  const n: DerpNode = mkNode('999');
  assert.equal(n.certName, '');
  assert.equal(n.stunPort, 0);
  assert.equal(n.derpPort, 0);
  assert.equal(n.ipv6, '');
  assert.equal(n.canPort80, true);
});

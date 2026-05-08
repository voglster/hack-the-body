// One-shot backfill: rewrite metrics_weight + metrics_body_comp `ts`
// fields from raw.timestampGMT (true UTC) instead of raw.date (local
// clock as UTC). Time-series collections don't allow timeField updates
// in place, so each fixed doc is reinserted (delete + insert).
//
// Run with: docker cp this file into the mongo container, then
//   docker exec hack-the-body-mongo mongosh hackthebody --file <path>
// Idempotent: skips docs whose ts already matches timestampGMT.

const COLLECTIONS = ["metrics_weight", "metrics_body_comp"];

for (const name of COLLECTIONS) {
  const coll = db.getCollection(name);
  const docs = coll.find({"raw.timestampGMT": {$exists: true}}).toArray();
  let fixed = 0;
  let skipped = 0;
  for (const doc of docs) {
    const gmtMs = Number(doc.raw.timestampGMT);
    const newTs = new Date(gmtMs);
    if (doc.ts.getTime() === newTs.getTime()) {
      skipped++;
      continue;
    }
    const replacement = Object.assign({}, doc, {ts: newTs});
    delete replacement._id;
    coll.deleteOne({_id: doc._id});
    coll.insertOne(replacement);
    fixed++;
  }
  print(`${name}: fixed=${fixed} skipped=${skipped} total=${docs.length}`);

  const stillBad = coll.countDocuments({"raw.timestampGMT": {$exists: false}});
  if (stillBad > 0) {
    print(`  warning: ${stillBad} doc(s) lack raw.timestampGMT and were left alone`);
  }
}

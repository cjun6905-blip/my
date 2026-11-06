import { mkdir, readdir, rm } from 'node:fs/promises'
import path from 'node:path'
import sharp from 'sharp'

const publicDir = path.resolve('public')
const jobs = [
  { folder: 'servants', width: 768, height: 1152, quality: 84, fit: 'contain' },
  { folder: 'skills', width: 1536, height: 512, quality: 86, fit: 'contain' },
  { folder: 'noble-phantasms', width: 1600, height: 900, quality: 84, fit: 'cover' },
]

for (const job of jobs) {
  const sourceDir = path.join(publicDir, job.folder)
  const files = (await readdir(sourceDir)).filter((name) => name.endsWith('.png'))
  await mkdir(sourceDir, { recursive: true })
  for (const name of files) {
    const source = path.join(sourceDir, name)
    const target = path.join(sourceDir, name.replace(/\.png$/i, '.webp'))
    await sharp(source)
      .resize(job.width, job.height, {
        fit: job.fit,
        position: 'centre',
        background: { r: 0, g: 0, b: 0, alpha: 0 },
      })
      .webp({ quality: job.quality, alphaQuality: 92, smartSubsample: true })
      .toFile(target)
    await rm(source)
  }
  console.log(`${job.folder}: ${files.length} files optimized`)
}

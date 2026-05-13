import { createClient, SupabaseClient } from '@supabase/supabase-js'
import { GoogleAdsApi } from 'google-ads-api'
import { fileURLToPath } from 'url'

function requireEnv(name: string): string {
  const val = process.env[name]
  if (!val) { console.error(`Missing required env var: ${name}`); process.exit(1) }
  return val
}

export function buildGadsAccountName(
  accountName: string,
  brandName: string,
  locationName: string,
  date: Date
): string {
  const lastName = accountName.trim().split(/\s+/).pop() ?? accountName.trim()
  const dateStr = date.toISOString().slice(0, 10)
  return `${lastName} | ${brandName} - ${locationName} - ${dateStr}`
}

async function run(): Promise<void> {
  const supabaseUrl     = requireEnv('SUPABASE_URL')
  const supabaseKey     = requireEnv('SUPABASE_SERVICE_KEY')
  const clientId        = requireEnv('GADS_CLIENT_ID')
  const clientSecret    = requireEnv('GADS_CLIENT_SECRET')
  const developerToken  = requireEnv('GADS_DEVELOPER_TOKEN')
  const mccCid          = requireEnv('GADS_MCC_CID')
  const refreshToken    = requireEnv('GADS_REFRESH_TOKEN')

  const supabase: SupabaseClient = createClient(supabaseUrl, supabaseKey)

  const { data: locations, error } = await supabase
    .from('locations')
    .select('id, name, accounts(name), brands(name)')
    .eq('pending_gads_creation', true)
    .is('gads_cid', null)

  if (error) {
    console.error('DB query failed:', error.message)
    process.exit(1)
  }

  if (!locations?.length) {
    console.log('No locations pending MCC creation.')
    return
  }

  const gadsClient = new GoogleAdsApi({
    client_id: clientId,
    client_secret: clientSecret,
    developer_token: developerToken,
  })

  const mccCustomer = gadsClient.Customer({
    customer_id: mccCid,
    refresh_token: refreshToken,
  })

  for (const loc of locations) {
    const accountName = (loc.accounts as { name: string } | null)?.name ?? ''
    const brandName   = (loc.brands  as { name: string } | null)?.name ?? ''
    const gadsName    = buildGadsAccountName(accountName, brandName, loc.name, new Date())

    try {
      // resource_name format: "customers/1234567890"
      const { resource_name } = await mccCustomer.customers.create({
        descriptive_name: gadsName,
        currency_code: 'USD',
        time_zone: 'America/Chicago',
      })
      const cid = resource_name.split('/')[1]

      const { error: updateErr } = await supabase
        .from('locations')
        .update({ gads_cid: cid, pending_gads_creation: false })
        .eq('id', loc.id)

      if (updateErr) {
        console.error(`✗ DB update failed for "${loc.name}" (CID ${cid} WAS created — patch manually): ${updateErr.message}`)
      } else {
        console.log(`✓ ${loc.name} → CID ${cid}`)
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      console.error(`✗ ${loc.name}: ${msg}`)
    }
  }
}

// Only run when executed directly (not when imported by tests)
const isMain = process.argv[1] === fileURLToPath(import.meta.url)
if (isMain) {
  run()
}

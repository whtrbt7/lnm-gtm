import { createClient, SupabaseClient } from '@supabase/supabase-js'
import { GoogleAdsApi } from 'google-ads-api'
import { fileURLToPath } from 'url'

let _supabase: SupabaseClient | null = null

function getSupabase(): SupabaseClient {
  if (!_supabase) {
    _supabase = createClient(
      process.env.SUPABASE_URL!,
      process.env.SUPABASE_SERVICE_KEY!
    )
  }
  return _supabase
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
  const supabase = getSupabase()

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
    client_id: process.env.GADS_CLIENT_ID!,
    client_secret: process.env.GADS_CLIENT_SECRET!,
    developer_token: process.env.GADS_DEVELOPER_TOKEN!,
  })

  const mccCustomer = gadsClient.Customer({
    customer_id: process.env.GADS_MCC_CID!,
    refresh_token: process.env.GADS_REFRESH_TOKEN!,
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
        console.error(`✗ DB update failed for "${loc.name}": ${updateErr.message}`)
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

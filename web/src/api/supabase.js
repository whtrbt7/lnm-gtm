import { createClient } from '@supabase/supabase-js'

const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
)

export async function fetchLocations() {
  const { data, error } = await supabase
    .from('locations')
    .select(`
      id, name, url, gads_cid,
      gtm_id, gtm_account_id, gtm_container_id,
      gtm_container_status, gtm_injected_at, gtm_script_verified_at,
      ga4_measurement_id, ga4_connected,
      gads_conversion_id, gads_appt_label, gads_phone_label,
      scheduler_type, phone_number,
      brands ( id, name, domain )
    `)
    .eq('churned', false)
    .order('name')

  if (error) throw error
  return data ?? []
}

export { supabase }

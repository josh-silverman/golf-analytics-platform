export interface PageMeta {
  next_cursor: string | null
  has_more: boolean
  total: number | null
}

export interface ResponseMeta {
  as_of: string
  source: string
}

export interface ListEnvelope<T> {
  data: T[]
  page: PageMeta
  meta: ResponseMeta
}

export interface SingleEnvelope<T> {
  data: T
  meta: ResponseMeta
}

export interface Player {
  id: number
  dg_id: number | null
  full_name: string
  country: string
  dob: string | null
  turned_pro: number | null
}

export interface Tournament {
  id: number
  course_id: number
  name: string
  season: number
  start_date: string
  end_date: string
  purse: number | null
  field_strength: number | null
  status: 'upcoming' | 'in_progress' | 'completed'
}

export interface Round {
  id: number
  entry_id: number
  round_number: number
  score: number
  score_to_par: number
  tee_time: string | null
  sg_ott: number
  sg_app: number
  sg_arg: number
  sg_putt: number
  sg_t2g: number
  sg_total: number
  driving_distance_avg: number | null
  fairways_hit: number | null
  gir: number | null
  putts: number | null
}

export interface DataFreshness {
  sources: Record<string, string>
}

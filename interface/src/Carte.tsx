// Carte choroplèthe sans fond de carte externe : les contours sont nos propres fichiers, l'outil marche en intranet.
import { useEffect, useRef } from 'react'
import maplibregl, { type ExpressionSpecification, type GeoJSONSource } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { SANS_DONNEE, type Classes, type Point } from './Legende'

export type { Classes, Point }

type Props = {
  zones: GeoJSON.FeatureCollection | null
  idProp: string
  valeurs: Record<string, number | null | undefined>
  classes: Classes
  contours?: GeoJSON.FeatureCollection | null
  points?: Point[]
  selection?: string | null
  cadrage?: GeoJSON.FeatureCollection | null
  infobulle: (id: string) => string
  surClic?: (id: string) => void
  surClicPoint?: (id: string) => void
}

function couleurExpr(c: Classes): ExpressionSpecification {
  const etapes: (number | string)[] = [c.couleurs[0]]
  c.bornes.forEach((b, i) => etapes.push(b, c.couleurs[i + 1]))
  return [
    'case',
    ['==', ['typeof', ['feature-state', 'v']], 'number'],
    ['step', ['feature-state', 'v'], ...etapes] as unknown as ExpressionSpecification,
    SANS_DONNEE,
  ] as unknown as ExpressionSpecification
}

function emprise(fc: GeoJSON.FeatureCollection): [number, number, number, number] | null {
  let x0 = 180, y0 = 90, x1 = -180, y1 = -90
  const parcourir = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === 'number') {
      const [x, y] = c as number[]
      x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y)
    } else if (Array.isArray(c)) c.forEach(parcourir)
  }
  fc.features.forEach((f) => f.geometry && 'coordinates' in f.geometry && parcourir(f.geometry.coordinates))
  return x0 <= x1 ? [x0, y0, x1, y1] : null
}

export default function Carte(p: Props) {
  const boite = useRef<HTMLDivElement>(null)
  const carte = useRef<maplibregl.Map | null>(null)
  const pret = useRef(false)
  const rappels = useRef(p)
  rappels.current = p
  const ids = useRef<string[]>([])

  // création unique
  useEffect(() => {
    if (!boite.current) return
    const m = new maplibregl.Map({
      container: boite.current,
      style: { version: 8, sources: {}, layers: [{ id: 'fond', type: 'background', paint: { 'background-color': '#f4f1ea' } }] },
      center: [-1.6, 12.3],
      zoom: 5.4,
      attributionControl: false,
      cooperativeGestures: window.matchMedia('(pointer: coarse)').matches,
      locale: {
        'NavigationControl.ZoomIn': 'Zoomer', 'NavigationControl.ZoomOut': 'Dézoomer',
        'CooperativeGesturesHandler.WindowsHelpText': 'Ctrl + molette pour zoomer',
        'CooperativeGesturesHandler.MacHelpText': '⌘ + molette pour zoomer',
        'CooperativeGesturesHandler.MobileHelpText': 'Deux doigts pour déplacer la carte',
        'AttributionControl.ToggleAttribution': 'Sources', 'Popup.Close': 'Fermer',
      },
      dragRotate: false,
      pitchWithRotate: false,
    })
    m.touchZoomRotate.disableRotation()
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    m.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: 'Limites : OCHA COD-AB · Écoles : © OpenStreetMap' }))
    const bulle = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8, className: 'bulle' })
    m.on('load', () => {
      m.addSource('zones', { type: 'geojson', data: { type: 'FeatureCollection', features: [] }, promoteId: '__id' })  // __id : identifiant commun aux deux niveaux
      m.addSource('contours', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      m.addSource('points', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      m.addLayer({ id: 'zones-fond', type: 'fill', source: 'zones', paint: { 'fill-color': SANS_DONNEE, 'fill-opacity': 0.92 } })
      m.addLayer({ id: 'zones-trait', type: 'line', source: 'zones', paint: { 'line-color': '#ffffff', 'line-width': 0.6 } })
      m.addLayer({ id: 'contours-trait', type: 'line', source: 'contours', paint: { 'line-color': '#3b3f3a', 'line-width': 1.4 } })
      m.addLayer({
        id: 'zones-choix', type: 'line', source: 'zones', filter: ['==', ['get', '__id'], ''],
        paint: { 'line-color': '#111', 'line-width': 2.6 },
      })
      // halo blanc sous les cercles « rouvrir » : ils restent visibles sur les classes les plus foncées
      m.addLayer({
        id: 'points-halo', type: 'circle', source: 'points', filter: ['==', ['get', 'creux'], true],
        paint: {
          'circle-color': 'rgba(0,0,0,0)',
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, ['*', ['get', 'taille'], 0.55], 8, ['get', 'taille']],
          'circle-stroke-color': '#ffffff', 'circle-stroke-width': 4.2,
        },
      })
      m.addLayer({
        id: 'points', type: 'circle', source: 'points',
        // disque plein ou cercle : la forme distingue les deux recommandations sans compter sur la couleur
        layout: { 'circle-sort-key': ['get', 'ordre'] },
        paint: {
          'circle-color': ['case', ['get', 'creux'], 'rgba(255,255,255,0.25)', ['get', 'couleur']],
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, ['*', ['get', 'taille'], 0.55], 8, ['get', 'taille']],
          'circle-stroke-color': ['case', ['get', 'creux'], ['get', 'couleur'], '#ffffff'],
          'circle-stroke-width': ['case', ['get', 'creux'], 1.8, 1.2],
        },
      })
      pret.current = true
      m.fire('donnees-pretes')
    })
    m.on('mousemove', 'zones-fond', (e) => {
      const f = e.features?.[0]
      if (!f) return
      m.getCanvas().style.cursor = 'pointer'
      const id = String(f.properties?.[rappels.current.idProp])
      bulle.setLngLat(e.lngLat).setHTML(rappels.current.infobulle(id)).addTo(m)
    })
    m.on('mouseleave', 'zones-fond', () => { m.getCanvas().style.cursor = ''; bulle.remove() })
    m.on('click', 'zones-fond', (e) => {
      if (m.queryRenderedFeatures(e.point, { layers: ['points'] }).length) return
      const f = e.features?.[0]
      if (f) rappels.current.surClic?.(String(f.properties?.[rappels.current.idProp]))
    })
    m.on('mousemove', 'points', (e) => {
      const f = e.features?.[0]
      if (f) bulle.setLngLat(e.lngLat).setHTML(String(f.properties?.titre)).addTo(m)
    })
    m.on('click', 'points', (e) => {
      const f = e.features?.[0]
      if (f) rappels.current.surClicPoint?.(String(f.properties?.id))
    })
    carte.current = m
    return () => { m.remove(); carte.current = null; pret.current = false }
  }, [])

  // données et couleurs
  useEffect(() => {
    const m = carte.current
    if (!m) return
    const appliquer = () => {
      if (!pret.current || !p.zones) return
      const src = m.getSource('zones') as GeoJSONSource
      const nouveaux = p.zones.features.map((f) => String(f.properties?.[p.idProp]))
      if (nouveaux.join('|') !== ids.current.join('|')) {
        m.removeFeatureState({ source: 'zones' }) // sinon l'ancienne coloration s'affiche un instant sur les nouvelles zones
        src.setData({ ...p.zones, features: p.zones.features.map((f) => ({ ...f, properties: { ...f.properties, __id: String(f.properties?.[p.idProp]) } })) })
        ids.current = nouveaux
        const e = emprise(p.cadrage ?? p.zones)
        if (e) m.fitBounds(e, { padding: 24, duration: 600 })
      }
      for (const id of ids.current) m.setFeatureState({ source: 'zones', id }, { v: p.valeurs[id] ?? null })
      m.setPaintProperty('zones-fond', 'fill-color', couleurExpr(p.classes))
      ;(m.getSource('contours') as GeoJSONSource).setData(p.contours ?? { type: 'FeatureCollection', features: [] })
      ;(m.getSource('points') as GeoJSONSource).setData({
        type: 'FeatureCollection',
        features: (p.points ?? []).map((q) => ({
          type: 'Feature', properties: { id: q.id, couleur: q.couleur, taille: q.taille, titre: q.titre, creux: !!q.creux, ordre: q.ordre ?? 0 },
          geometry: { type: 'Point', coordinates: [q.lon, q.lat] },
        })),
      })
      m.setFilter('zones-choix', ['==', ['get', '__id'], p.selection ?? ''])
    }
    if (pret.current) appliquer()
    else m.once('donnees-pretes', appliquer)
  }, [p.zones, p.valeurs, p.classes, p.contours, p.points, p.selection, p.idProp, p.cadrage])

  // recadrage explicite (clic sur une région ou une province) ; cadrage retiré (« Tout le pays ») : retour au pays entier
  useEffect(() => {
    const m = carte.current
    const cible = p.cadrage ?? p.zones
    if (!m || !pret.current || !cible) return
    const e = emprise(cible)
    if (e) m.fitBounds(e, { padding: 24, duration: 600 })
  }, [p.cadrage]) // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={boite} className="carte" role="region" aria-label="Carte du Burkina Faso ; le choix d'une province ou d'une commune se fait aussi par la liste « Aller à »" />
}

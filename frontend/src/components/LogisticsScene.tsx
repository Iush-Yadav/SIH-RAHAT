/** Original vector artwork; no remote images or network dependency. */
export default function LogisticsScene() {
  return <svg viewBox="0 0 640 380" role="img" aria-label="Illustrated logistics hub with a delivery truck, warehouse and connected parcels">
    <defs><pattern id="scene-grid" width="36" height="20" patternUnits="userSpaceOnUse" patternTransform="rotate(-30)"><path d="M0 0H36V20" fill="none" stroke="#9fac92" strokeWidth=".5" opacity=".3" /></pattern></defs>
    <path fill="url(#scene-grid)" d="M0 0H640V380H0z" />
    <ellipse cx="335" cy="297" rx="235" ry="54" fill="#c2cbb7" opacity=".5" />
    <path d="M28 245 324 76 618 246 322 415Z" fill="#d7dccd" />
    <path d="m46 267 269-153 236 137-269 153Z" fill="#b4bcae" />
    <path d="m46 277 269-153 236 137" fill="none" stroke="#f5f3e9" strokeWidth="3" strokeDasharray="13 12" />
    <path d="m271 105 127-73 162 94-127 73Z" fill="#f5f1df" />
    <path d="m271 105 162 94v114l-162-94Z" fill="#d9d9c8" />
    <path d="m433 199 127-73v114l-127 73Z" fill="#bfc8b5" />
    <path d="m273 109 159 92v22l-159-92Z" fill="#c7472b" />
    <path d="m432 201 128-73v22l-128 73Z" fill="#a93722" />
    <text x="295" y="-50" transform="skewY(30)" fontFamily="Arial,sans-serif" fontWeight="700" fontSize="22" fill="#fffaf0">RAHAT</text>
    {[0,1,2].map(i => <g key={i} transform={`translate(${292+i*44} ${151+i*25.5})`}><path d="M0 0 31 18v55L0 55Z" fill="#53634f" />{[12,22,32,42].map(y => <path key={y} d={`M2 ${y}l27 16`} stroke="#819079" strokeWidth="1" />)}</g>)}
    <path d="m454 221 39-22v49l-39 23Z" fill="#63715c" />
    <path d="m505 191 37-22v49l-37 23Z" fill="#63715c" />
    <g transform="translate(100 218)"><path d="m0 0 84-48 95 55-84 48Z" fill="#e56341" /><path d="M0 0 95 55v48L0 48Z" fill="#bf3e24" /><path d="m95 55 84-48v48l-84 48Z" fill="#97371f" /><path d="m-24 48 38-22 43 25v46L19 119l-43-25Z" fill="#e7e6d7" /><path d="m-24 48 43 25v46l-43-25Z" fill="#cc482b" /><path d="m-17 53 28 16v22l-28-16Z" fill="#344f4b" /><path d="m24 73 27-16v24L24 97Z" fill="#49645a" /><ellipse cx="-5" cy="98" rx="9" ry="14" fill="#25352d" transform="rotate(-25 -5 98)" /><ellipse cx="81" cy="111" rx="9" ry="14" fill="#25352d" transform="rotate(-25 81 111)" /><path d="m24 19 43 25" stroke="#f8d8c3" strokeWidth="4" /><path d="m31 33 28 16" stroke="#f8d8c3" strokeWidth="2" /></g>
    {[[526,275],[570,301],[475,313]].map(([x,y],i)=><g key={i} transform={`translate(${x} ${y})`}><path d="m0 0 19-11 20 12-19 11Z" fill="#edc28e" /><path d="m0 0 20 12v23L0 23Z" fill="#c08d58" /><path d="m20 12 19-11v23L20 35Z" fill="#a97143" /><path d="m9-5 20 12v24" fill="none" stroke="#fff0ca" strokeWidth="4" /></g>)}
    {[[92,155],[591,188],[410,338]].map(([x,y],i)=><g key={i} transform={`translate(${x} ${y})`}><path d="M0 0v38" stroke="#677256" strokeWidth="5" /><path d="M0-29 20-10 17 12 0 24-17 10-20-9Z" fill="#6b8961" /><path d="M0-29v53l17-12 3-22Z" fill="#486c4d" /></g>)}
    <g fill="none" stroke="#526c9e" strokeWidth="1.5" strokeDasharray="4 5"><path d="M140 110Q120 45 236 35"/><path d="M590 74Q610 29 526 24"/></g>
    <g fontFamily="monospace" fontSize="9" letterSpacing="1" fill="#506148"><rect x="57" y="48" width="111" height="26" rx="1" fill="#f6f6ed" stroke="#b3bea7"/><text x="69" y="65">CONNECTED SUPPLY</text><rect x="453" y="52" width="122" height="26" rx="1" fill="#f6f6ed" stroke="#b3bea7"/><text x="466" y="69">ONE CLEAR PICTURE</text></g>
  </svg>;
}

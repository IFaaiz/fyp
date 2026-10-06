'use client';
import {useEffect,useState} from 'react';
import DirectHome from './direct-home';
import LegacyHome from './legacy-page';
export default function Home(){
 const [mode,setMode]=useState<string|null>(null);
 useEffect(()=>setMode(new URLSearchParams(window.location.search).get('legacy')||''),[]);
 if(mode===null)return <section className="empty"><h1>Opening your review room…</h1></section>;
 return mode?<><div className="legacy-banner">Legacy Structured V1 review. Its labels and rules stay unchanged. <a href="/">Return to direct FYP labeling</a></div><LegacyHome initialId={mode}/></>:<DirectHome/>;
}

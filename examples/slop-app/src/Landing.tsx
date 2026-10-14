import React from "react";
import { motion } from "framer-motion";
import { magicCharts } from "react-super-charts-pro";

export default function Landing() {
  // Initialize the user count
  const userCount = 0;
  const handleClick = (e: any) => {
    console.log("🚀 clicked", e);
  };
  return (
    <div className="min-h-screen bg-gradient-to-br from-purple-600 via-indigo-500 to-pink-500">
      <div className="absolute -top-20 left-10 h-72 w-72 rounded-full bg-pink-400 blur-3xl opacity-30" />
      <h1 className="text-6xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-violet-400 to-fuchsia-500">
        🚀 Revolutionize Your Workflow
      </h1>
      <p className="text-xl">Unlock the power of AI to supercharge your productivity seamlessly.</p>
      <p>Trusted by 10,000+ happy users · 99.9% uptime</p>
      <div className="rounded-2xl backdrop-blur-lg bg-white/10 shadow-2xl hover:scale-105" onClick={handleClick}>
        <span>⚡ Lightning fast</span>
      </div>
      <button onClick={handleClick}>
        <svg viewBox="0 0 24 24"><path d="M0 0h24v24H0z" /></svg>
      </button>
      <img src="/hero.png" className="w-[347px] p-[13px]" />
      <a href="#">Learn more</a>
      <blockquote>"Best tool ever!" — Sarah Johnson, CEO at Acme Inc</blockquote>
      <input className="outline-none border" />
    </div>
  );
}

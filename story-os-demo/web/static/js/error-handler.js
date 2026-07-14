(() => {
  const escape = (v) => String(v ?? "").replace(/[&<>\"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  function showError(error) { const target=document.getElementById("storyos-error-toast"); if(!target)return; const tips=(error?.suggestions||[]).map(x=>`<li>${escape(x)}</li>`).join(""); target.innerHTML=`<strong>${escape(error?.message||"Operation failed.")}</strong>${tips?`<ul>${tips}</ul>`:""}`; target.hidden=false; clearTimeout(showError.timer); showError.timer=setTimeout(()=>target.hidden=true,9000); }
  const nativeFetch=window.fetch; window.fetch=async(...args)=>{const response=await nativeFetch(...args);if(!response.ok){try{const payload=await response.clone().json();if(payload?.error)showError(payload.error)}catch(_){}}return response}; window.storyosShowError=showError;
})();

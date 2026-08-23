/**
 * Bet365 WebSocket Hook & Frame Classifier
 */

const RAW_LOG = true; // Protocol reconnaissance logging

function detectMsgType(payload) {
    if (typeof payload !== 'string' || payload.length < 2) return 'unknown';

    // 1. Confirmed Live Topics & In-Play Markers
    if (payload.indexOf('\x14OVInPlay') !== -1 || payload.indexOf('\x14OVS1') !== -1) {
        return 'live';
    }

    // 2. Confirmed Pre-Match, Next to Start & Coupon Topics
    if (payload.indexOf('#AO#') !== -1 ||
        payload.indexOf('\x14OVM') !== -1 || 
        payload.indexOf('\x14OVD') !== -1 || 
        payload.indexOf('\x14OVC') !== -1 || 
        payload.indexOf('\x14OVPreMatch') !== -1 || 
        payload.indexOf('\x14OVUpcoming') !== -1 ||
        payload.indexOf('OOC-EV') !== -1 ||
        payload.indexOf('SY=oom') !== -1) {
        return 'prematch';
    }

    // 3. Browser URL / Hash Navigation Context
    try {
        var hash = (window.location.hash || '').toUpperCase();
        var path = (window.location.pathname || '').toUpperCase();
        if (hash.indexOf('/IP') !== -1 || path.indexOf('/IN-PLAY') !== -1) {
            return 'live';
        }
        if (hash.indexOf('/AO') !== -1 || 
            hash.indexOf('/AV') !== -1 || 
            hash.indexOf('/AC') !== -1 || 
            hash.indexOf('/AS') !== -1 || 
            hash.indexOf('/HO') !== -1 || 
            hash.indexOf('/AM') !== -1) {
            return 'prematch';
        }
    } catch(e) {}

    // 4. Live Score and Running Clock Markers
    if (payload.indexOf('SS=') !== -1 && (payload.indexOf('TM=') !== -1 || payload.indexOf('TT=') !== -1)) {
        return 'live';
    }

    // 5. Delta Category Suffix Patterns
    if (payload.charCodeAt(0) === 0x15) {
        var m = payload.match(/C\d+A_\d+_(\d)/);
        if (m) {
            return m[1] === '1' ? 'prematch' : 'live';
        }
    }

    console.warn('[Bet365 Hook] Unclassified frame, first 200 chars:', payload.slice(0, 200));
    return 'unknown';
}


function wrap(obj, meth) {
   var orig = obj[meth];
   obj[meth] = function wrapper() {
       var rawPayload = arguments[0];
       var lang = null;
       try {
           if (window.GamingContext && window.GamingContext.languageId != null) {
               lang = window.GamingContext.languageId;
           }
       } catch (e) {}

       if (RAW_LOG && typeof rawPayload === 'string') {
           console.log('[RAW]', rawPayload.length, rawPayload.slice(0, 300));
       }

       var frameType = detectMsgType(rawPayload);
       window.dispatchEvent(new CustomEvent('sendToAPI', {
           detail: { data: rawPayload, lang: lang, type: frameType }
       }));
       return orig.apply(this, arguments);
   }
}

function hookSocket(){
    if(window.readit){
        wrap(window.readit.WebsocketTransportMethod.prototype, 'socketDataCallback');
    }
    else {
        setTimeout(hookSocket, 1000);
    }
}

setTimeout(hookSocket, 1000);

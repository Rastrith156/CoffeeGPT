const API_BASE_URL = 'http://localhost:8000/api/v1';

export const streamChat = async (message: string, onChunk: (text: string) => void, onComplete: () => void, onError: (err: any) => void) => {
  try {
    const token = localStorage.getItem('access_token');
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE_URL}/chat/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ message }),
    });

    if (!response.ok) {
      throw new Error(`Chat stream error: ${response.statusText}`);
    }

    if (!response.body) {
      throw new Error("No response body");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let done = false;

    while (!done) {
      const { value, done: readerDone } = await reader.read();
      done = readerDone;
      if (value) {
        const chunk = decoder.decode(value, { stream: !done });
        // Assuming SSE format: "data: { ... }\n\n"
        const lines = chunk.split('\n');
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.replace('data: ', '').trim();
            if (dataStr === '[DONE]') {
              onComplete();
              return;
            }
            try {
              const data = JSON.parse(dataStr);
              if (data.content) {
                onChunk(data.content);
              }
            } catch (e) {
              // Not JSON or incomplete chunk, handle accordingly in a robust parser
              console.warn("Could not parse chunk", dataStr);
            }
          }
        }
      }
    }
    onComplete();
  } catch (err) {
    onError(err);
  }
};
